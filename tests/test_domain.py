"""Domain layer: immutable value objects for billing + tickets.

The domain is pure data — no business rules live here. Eligibility, caps, and
authorization belong to the policy gate, not the records. These tests pin the
invariants the rest of the system relies on: immutability, non-negative money,
and a small set of derived read-only properties.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError
from relay.domain import (
    Channel,
    Customer,
    Invoice,
    InvoiceStatus,
    Subscription,
    SubscriptionStatus,
    Ticket,
    dollars,
)

UTC = dt.UTC


def _customer() -> Customer:
    return Customer(
        id="cus_1",
        email="ada@example.com",
        name="Ada Lovelace",
        created_at=dt.datetime(2025, 1, 1, tzinfo=UTC),
    )


def test_customer_is_immutable() -> None:
    c = _customer()
    with pytest.raises(ValidationError):
        c.email = "evil@example.com"  # type: ignore[misc]


def test_money_is_non_negative() -> None:
    with pytest.raises(ValidationError):
        Invoice(
            id="in_1",
            customer_id="cus_1",
            subscription_id="sub_1",
            amount_cents=-100,
            currency="usd",
            status=InvoiceStatus.PAID,
            created_at=dt.datetime(2025, 1, 1, tzinfo=UTC),
        )


def test_invoice_refundable_remainder() -> None:
    inv = Invoice(
        id="in_1",
        customer_id="cus_1",
        subscription_id="sub_1",
        amount_cents=5000,
        currency="usd",
        status=InvoiceStatus.PAID,
        created_at=dt.datetime(2025, 1, 1, tzinfo=UTC),
        refunded_cents=2000,
    )
    assert inv.refundable_remaining_cents == 3000


def test_invoice_fully_refunded_remainder_is_zero() -> None:
    inv = Invoice(
        id="in_1",
        customer_id="cus_1",
        subscription_id="sub_1",
        amount_cents=5000,
        currency="usd",
        status=InvoiceStatus.REFUNDED,
        created_at=dt.datetime(2025, 1, 1, tzinfo=UTC),
        refunded_cents=5000,
    )
    assert inv.refundable_remaining_cents == 0


def test_refunded_cannot_exceed_amount() -> None:
    with pytest.raises(ValidationError):
        Invoice(
            id="in_1",
            customer_id="cus_1",
            subscription_id="sub_1",
            amount_cents=5000,
            currency="usd",
            status=InvoiceStatus.PAID,
            created_at=dt.datetime(2025, 1, 1, tzinfo=UTC),
            refunded_cents=6000,
        )


def test_subscription_is_active_flag() -> None:
    active = Subscription(
        id="sub_1",
        customer_id="cus_1",
        plan="pro",
        status=SubscriptionStatus.ACTIVE,
        amount_cents=2000,
        currency="usd",
        current_period_end=dt.datetime(2025, 2, 1, tzinfo=UTC),
    )
    canceled = active.model_copy(update={"status": SubscriptionStatus.CANCELED})
    assert active.is_active is True
    assert canceled.is_active is False


def test_ticket_roundtrips_json() -> None:
    t = Ticket(
        id="tkt_1",
        customer_id="cus_1",
        subject="Refund please",
        body="I was charged twice this month.",
        channel=Channel.EMAIL,
        created_at=dt.datetime(2025, 1, 5, tzinfo=UTC),
    )
    restored = Ticket.model_validate_json(t.model_dump_json())
    assert restored == t


def test_dollars_formats_cents() -> None:
    assert dollars(0) == "$0.00"
    assert dollars(5) == "$0.05"
    assert dollars(12345) == "$123.45"
