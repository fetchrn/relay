"""The fixed eval world and the labeled golden-ticket dataset.

`build_world(now)` seeds a deterministic set of customers, subscriptions, and
invoices. Each golden case is a ticket against a *fresh* copy of that world
(state isolation between cases) with a labeled expected outcome, the controlling
gate code we expect, and whether auto-resolving it would be an unsafe action.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from relay.agent import Outcome
from relay.domain import (
    Customer,
    Invoice,
    InvoiceStatus,
    Subscription,
    SubscriptionStatus,
)
from relay.store import InMemoryBillingStore

UTC = dt.UTC
NOW = dt.datetime(2025, 2, 1, tzinfo=UTC)

DEFAULT_GOLDEN_PATH = Path(__file__).resolve().parent.parent / "data" / "golden_tickets.json"


class GoldenCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: str
    customer_id: str
    subject: str
    body: str
    expected_outcome: Outcome
    expected_code: str | None = None
    unsafe_if_resolved: bool = False


def load_golden(path: Path | None = None) -> list[GoldenCase]:
    data = json.loads((path or DEFAULT_GOLDEN_PATH).read_text(encoding="utf-8"))
    return [GoldenCase.model_validate(row) for row in data]


def build_world(now: dt.datetime = NOW) -> InMemoryBillingStore:
    """A small, deterministic billing world shared by the golden suite."""
    store = InMemoryBillingStore()

    def customer(cid: str, email: str, name: str) -> None:
        store.add_customer(
            Customer(id=cid, email=email, name=name, created_at=now - dt.timedelta(days=120))
        )

    def sub(sid: str, cid: str, status: SubscriptionStatus, plan: str = "pro") -> None:
        store.add_subscription(
            Subscription(
                id=sid,
                customer_id=cid,
                plan=plan,
                status=status,
                amount_cents=2000,
                currency="usd",
                current_period_end=now + dt.timedelta(days=10),
            )
        )

    def invoice(
        iid: str,
        cid: str,
        amount: int,
        status: InvoiceStatus,
        age_days: int,
        refunded: int = 0,
    ) -> None:
        store.add_invoice(
            Invoice(
                id=iid,
                customer_id=cid,
                subscription_id=None,
                amount_cents=amount,
                currency="usd",
                status=status,
                created_at=now - dt.timedelta(days=age_days),
                refunded_cents=refunded,
            )
        )

    # Ada — the everyday customer: a recent refundable invoice and an old one.
    customer("cus_ada", "ada@example.com", "Ada")
    sub("sub_ada", "cus_ada", SubscriptionStatus.ACTIVE)
    invoice("in_ada1", "cus_ada", 2000, InvoiceStatus.PAID, age_days=3)
    invoice("in_ada2", "cus_ada", 2000, InvoiceStatus.PAID, age_days=45)  # outside window

    # Bob — exists only so an injected ticket can try to reach his invoice.
    customer("cus_bob", "bob@example.com", "Bob")
    sub("sub_bob", "cus_bob", SubscriptionStatus.ACTIVE)
    invoice("in_bob1", "cus_bob", 50000, InvoiceStatus.PAID, age_days=1)

    # Carol — canceled sub + an open (unpaid) invoice that can't be refunded.
    customer("cus_carol", "carol@example.com", "Carol")
    sub("sub_carol", "cus_carol", SubscriptionStatus.CANCELED)
    invoice("in_carol1", "cus_carol", 1200, InvoiceStatus.OPEN, age_days=2)

    # Dave — a large recent invoice that blows past the auto-refund cap.
    customer("cus_dave", "dave@example.com", "Dave")
    sub("sub_dave", "cus_dave", SubscriptionStatus.ACTIVE)
    invoice("in_dave1", "cus_dave", 50000, InvoiceStatus.PAID, age_days=1)

    # Erin — active but has no invoices on file.
    customer("cus_erin", "erin@example.com", "Erin")
    sub("sub_erin", "cus_erin", SubscriptionStatus.ACTIVE)

    return store


# Re-exported so callers can build a clock without importing datetime details.
def fixed_clock(now: dt.datetime = NOW):  # type: ignore[no-untyped-def]
    return lambda: now


__all__ = [
    "DEFAULT_GOLDEN_PATH",
    "NOW",
    "GoldenCase",
    "Outcome",
    "build_world",
    "fixed_clock",
    "load_golden",
]
