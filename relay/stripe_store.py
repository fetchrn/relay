"""A Stripe-backed billing store.

`StripeBillingStore` implements the same :class:`~relay.store.BillingStore`
protocol as the in-memory store, so the orchestrator and both gates are
unchanged when Relay is pointed at a real Stripe account. The mapping functions
(`to_customer` / `to_invoice` / `to_subscription`) are pure and unit-tested; the
store methods call an injected Stripe-like client (the real ``stripe`` module, or
a fake in tests).

Scope note: this is a reference adapter against Stripe's object shapes. A refund
targets an invoice's underlying charge and carries an idempotency key. A
production deployment should reconcile refund totals at the charge level rather
than trusting a single ``amount_refunded`` field — see docs/HONESTY.md.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from relay.domain import Customer, Invoice, InvoiceStatus, Subscription, SubscriptionStatus
from relay.store import BillingError, CancelReceipt, RefundReceipt

_INVOICE_STATUS = {
    "paid": InvoiceStatus.PAID,
    "open": InvoiceStatus.OPEN,
    "draft": InvoiceStatus.OPEN,
    "void": InvoiceStatus.UNCOLLECTIBLE,
    "uncollectible": InvoiceStatus.UNCOLLECTIBLE,
}
_SUB_STATUS = {
    "active": SubscriptionStatus.ACTIVE,
    "trialing": SubscriptionStatus.TRIALING,
    "past_due": SubscriptionStatus.PAST_DUE,
    "canceled": SubscriptionStatus.CANCELED,
    "unpaid": SubscriptionStatus.PAST_DUE,
}


def _ts(unix: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(unix, dt.UTC)


def to_customer(obj: dict[str, Any]) -> Customer:
    return Customer(
        id=obj["id"],
        email=obj.get("email") or "",
        name=obj.get("name") or "",
        created_at=_ts(obj["created"]),
    )


def to_invoice(obj: dict[str, Any]) -> Invoice:
    return Invoice(
        id=obj["id"],
        customer_id=obj["customer"],
        subscription_id=obj.get("subscription"),
        amount_cents=int(obj["amount_due"]),
        currency=obj.get("currency", "usd"),
        status=_INVOICE_STATUS.get(obj["status"], InvoiceStatus.UNCOLLECTIBLE),
        created_at=_ts(obj["created"]),
        refunded_cents=int(obj.get("amount_refunded", 0)),
    )


def to_subscription(obj: dict[str, Any]) -> Subscription:
    return Subscription(
        id=obj["id"],
        customer_id=obj["customer"],
        plan=obj.get("plan", "unknown"),
        status=_SUB_STATUS.get(obj["status"], SubscriptionStatus.CANCELED),
        amount_cents=int(obj.get("amount_cents", 0)),
        currency=obj.get("currency", "usd"),
        current_period_end=_ts(obj["current_period_end"]),
    )


class StripeBillingStore:
    """BillingStore backed by a Stripe-like client (dependency-injected)."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def get_customer(self, customer_id: str) -> Customer | None:
        raw = self._retrieve(self.client.Customer, customer_id)
        return to_customer(raw) if raw is not None else None

    def get_subscription(self, subscription_id: str) -> Subscription | None:
        raw = self._retrieve(self.client.Subscription, subscription_id)
        return to_subscription(raw) if raw is not None else None

    def get_subscriptions(self, customer_id: str) -> list[Subscription]:
        data = self.client.Subscription.list(customer=customer_id)["data"]
        return [to_subscription(s) for s in data]

    def get_invoice(self, invoice_id: str) -> Invoice | None:
        raw = self._retrieve(self.client.Invoice, invoice_id)
        return to_invoice(raw) if raw is not None else None

    def get_invoices(self, customer_id: str) -> list[Invoice]:
        data = self.client.Invoice.list(customer=customer_id)["data"]
        return [to_invoice(i) for i in data]

    def issue_refund(
        self, invoice_id: str, amount_cents: int, *, idempotency_key: str
    ) -> RefundReceipt:
        if amount_cents <= 0:
            raise BillingError("refund amount must be positive")
        raw = self._retrieve(self.client.Invoice, invoice_id)
        if raw is None:
            raise BillingError(f"unknown invoice {invoice_id!r}")
        charge = raw.get("charge")
        if not charge:
            raise BillingError(f"invoice {invoice_id!r} has no charge to refund")
        self.client.Refund.create(
            charge=charge, amount=amount_cents, idempotency_key=idempotency_key
        )
        already_refunded = int(raw.get("amount_refunded", 0))
        return RefundReceipt(
            invoice_id=invoice_id,
            amount_cents=amount_cents,
            idempotency_key=idempotency_key,
            refunded_total_cents=already_refunded + amount_cents,
        )

    def cancel_subscription(self, subscription_id: str, *, idempotency_key: str) -> CancelReceipt:
        self.client.Subscription.delete(subscription_id)
        return CancelReceipt(
            subscription_id=subscription_id,
            idempotency_key=idempotency_key,
            status=SubscriptionStatus.CANCELED,
        )

    @staticmethod
    def _retrieve(resource: Any, oid: str) -> dict[str, Any] | None:
        try:
            return resource.retrieve(oid)  # type: ignore[no-any-return]
        except (KeyError, LookupError):
            return None
