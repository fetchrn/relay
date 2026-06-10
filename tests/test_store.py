"""Billing store: the system of record.

The store is the only thing that mutates money or subscription state. The agent
never calls a mutating method directly — the orchestrator does, and only after
the policy + grounding gates authorize. The store is the *last* line of defense:
it enforces its own invariants (no over-refund, idempotency) so that even a bug
upstream can't double-charge or over-refund.

These tests pin the in-memory store, which is the default for the offline demo
and CI. The Stripe adapter is tested separately with an injected fake client.
"""

from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import pytest
from relay.domain import (
    Customer,
    Invoice,
    InvoiceStatus,
    Subscription,
    SubscriptionStatus,
)
from relay.store import BillingError, InMemoryBillingStore

UTC = dt.UTC


def _store() -> InMemoryBillingStore:
    store = InMemoryBillingStore()
    store.add_customer(
        Customer(
            id="cus_1",
            email="ada@example.com",
            name="Ada",
            created_at=dt.datetime(2025, 1, 1, tzinfo=UTC),
        )
    )
    store.add_customer(
        Customer(
            id="cus_2",
            email="bob@example.com",
            name="Bob",
            created_at=dt.datetime(2025, 1, 1, tzinfo=UTC),
        )
    )
    store.add_subscription(
        Subscription(
            id="sub_1",
            customer_id="cus_1",
            plan="pro",
            status=SubscriptionStatus.ACTIVE,
            amount_cents=2000,
            currency="usd",
            current_period_end=dt.datetime(2025, 2, 1, tzinfo=UTC),
        )
    )
    store.add_invoice(
        Invoice(
            id="in_1",
            customer_id="cus_1",
            subscription_id="sub_1",
            amount_cents=2000,
            currency="usd",
            status=InvoiceStatus.PAID,
            created_at=dt.datetime(2025, 1, 1, tzinfo=UTC),
        )
    )
    store.add_invoice(
        Invoice(
            id="in_2",
            customer_id="cus_2",
            subscription_id=None,
            amount_cents=999,
            currency="usd",
            status=InvoiceStatus.PAID,
            created_at=dt.datetime(2025, 1, 1, tzinfo=UTC),
        )
    )
    return store


def test_get_customer_found_and_missing() -> None:
    store = _store()
    assert store.get_customer("cus_1") is not None
    assert store.get_customer("nope") is None


def test_invoices_are_scoped_to_customer() -> None:
    store = _store()
    ids = {inv.id for inv in store.get_invoices("cus_1")}
    assert ids == {"in_1"}
    assert {inv.id for inv in store.get_invoices("cus_2")} == {"in_2"}


def test_issue_refund_reduces_remaining_and_marks_refunded() -> None:
    store = _store()
    receipt = store.issue_refund("in_1", 2000, idempotency_key="k1")
    assert receipt.amount_cents == 2000
    inv = store.get_invoice("in_1")
    assert inv is not None
    assert inv.refundable_remaining_cents == 0
    assert inv.status == InvoiceStatus.REFUNDED


def test_partial_refund_keeps_invoice_paid() -> None:
    store = _store()
    store.issue_refund("in_1", 500, idempotency_key="k1")
    inv = store.get_invoice("in_1")
    assert inv is not None
    assert inv.refundable_remaining_cents == 1500
    assert inv.status == InvoiceStatus.PAID


def test_refund_over_remaining_raises_and_does_not_mutate() -> None:
    store = _store()
    with pytest.raises(BillingError):
        store.issue_refund("in_1", 99999, idempotency_key="k1")
    inv = store.get_invoice("in_1")
    assert inv is not None
    assert inv.refundable_remaining_cents == 2000  # unchanged


def test_refund_non_positive_raises() -> None:
    store = _store()
    with pytest.raises(BillingError):
        store.issue_refund("in_1", 0, idempotency_key="k1")


def test_refund_is_idempotent_by_key() -> None:
    store = _store()
    r1 = store.issue_refund("in_1", 500, idempotency_key="same")
    r2 = store.issue_refund("in_1", 500, idempotency_key="same")
    assert r1 == r2
    inv = store.get_invoice("in_1")
    assert inv is not None
    # Applied exactly once, not twice.
    assert inv.refunded_cents == 500


def test_refund_unknown_invoice_raises() -> None:
    store = _store()
    with pytest.raises(BillingError):
        store.issue_refund("in_does_not_exist", 100, idempotency_key="k1")


def test_cancel_subscription_sets_status() -> None:
    store = _store()
    receipt = store.cancel_subscription("sub_1", idempotency_key="c1")
    assert receipt.subscription_id == "sub_1"
    sub = store.get_subscription("sub_1")
    assert sub is not None
    assert sub.status == SubscriptionStatus.CANCELED


def test_cancel_is_idempotent() -> None:
    store = _store()
    r1 = store.cancel_subscription("sub_1", idempotency_key="c1")
    r2 = store.cancel_subscription("sub_1", idempotency_key="c1")
    assert r1 == r2


def test_cancel_unknown_subscription_raises() -> None:
    store = _store()
    with pytest.raises(BillingError):
        store.cancel_subscription("sub_nope", idempotency_key="c1")


def test_concurrent_full_refunds_never_overdraw_one_invoice() -> None:
    """Regression for the Codex gate: the check-then-write must be atomic.

    `in_1` holds $20.00. Many threads each try to refund the *full* $20.00 with a
    distinct idempotency key — i.e. genuinely distinct refund attempts, not
    replays. Without a lock, several could pass the remaining-balance check before
    any write landed and overdraw the invoice. With the lock, exactly one wins;
    every other raises `BillingError`, and the invoice is never overdrawn.

    Reachable in the shipped default app because FastAPI runs the sync
    `/tickets` handler in a threadpool over one shared in-memory store.
    """
    store = _store()
    n = 32

    def attempt(i: int) -> bool:
        try:
            store.issue_refund("in_1", 2000, idempotency_key=f"race_{i}")
            return True
        except BillingError:
            return False

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(attempt, range(n)))

    assert sum(results) == 1  # exactly one distinct refund succeeded
    inv = store.get_invoice("in_1")
    assert inv is not None
    assert inv.refunded_cents == 2000  # never overdrawn
    assert inv.refundable_remaining_cents == 0
    assert inv.status is InvoiceStatus.REFUNDED
