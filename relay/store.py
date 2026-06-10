"""Billing store — the system of record for customers, subscriptions, invoices.

Two implementations share one :class:`BillingStore` protocol:

* :class:`InMemoryBillingStore` — deterministic, dependency-free. The default for
  the offline demo and for CI. No network, no API key.
* :class:`StripeBillingStore` — a thin adapter over a Stripe client (see
  ``relay.stripe_store``), injected so the read-mapping and refund call can be
  unit-tested with a fake.

Mutations (``issue_refund``, ``cancel_subscription``) are the store's
responsibility alone, and they are the *last* line of defense: they enforce
invariants (no over-refund, idempotency by key) regardless of what the agent or
the gates decided upstream. A bug in the agent must not be able to double-refund.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from relay.domain import Customer, Invoice, InvoiceStatus, Subscription, SubscriptionStatus


class BillingError(Exception):
    """Raised when a billing operation violates an invariant.

    The orchestrator treats any ``BillingError`` as a hard stop and escalates —
    it never swallows one and retries blindly.
    """


class RefundReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    invoice_id: str
    amount_cents: int
    idempotency_key: str
    refunded_total_cents: int


class CancelReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    subscription_id: str
    idempotency_key: str
    status: SubscriptionStatus


@runtime_checkable
class BillingStore(Protocol):
    """Read + (gated) write surface the orchestrator depends on."""

    def get_customer(self, customer_id: str) -> Customer | None: ...

    def get_subscription(self, subscription_id: str) -> Subscription | None: ...

    def get_subscriptions(self, customer_id: str) -> list[Subscription]: ...

    def get_invoice(self, invoice_id: str) -> Invoice | None: ...

    def get_invoices(self, customer_id: str) -> list[Invoice]: ...

    def issue_refund(
        self, invoice_id: str, amount_cents: int, *, idempotency_key: str
    ) -> RefundReceipt: ...

    def cancel_subscription(
        self, subscription_id: str, *, idempotency_key: str
    ) -> CancelReceipt: ...


class InMemoryBillingStore:
    """Deterministic in-memory billing store. The default store.

    Idempotency keys are honored per operation kind: a repeated call with a key
    already seen returns the recorded receipt and applies no further mutation.
    """

    def __init__(self) -> None:
        self._customers: dict[str, Customer] = {}
        self._subscriptions: dict[str, Subscription] = {}
        self._invoices: dict[str, Invoice] = {}
        self._refunds: dict[str, RefundReceipt] = {}
        self._cancels: dict[str, CancelReceipt] = {}

    # --- seeding -----------------------------------------------------------
    def add_customer(self, customer: Customer) -> None:
        self._customers[customer.id] = customer

    def add_subscription(self, subscription: Subscription) -> None:
        self._subscriptions[subscription.id] = subscription

    def add_invoice(self, invoice: Invoice) -> None:
        self._invoices[invoice.id] = invoice

    # --- reads -------------------------------------------------------------
    def get_customer(self, customer_id: str) -> Customer | None:
        return self._customers.get(customer_id)

    def get_subscription(self, subscription_id: str) -> Subscription | None:
        return self._subscriptions.get(subscription_id)

    def get_subscriptions(self, customer_id: str) -> list[Subscription]:
        return [s for s in self._subscriptions.values() if s.customer_id == customer_id]

    def get_invoice(self, invoice_id: str) -> Invoice | None:
        return self._invoices.get(invoice_id)

    def get_invoices(self, customer_id: str) -> list[Invoice]:
        return [i for i in self._invoices.values() if i.customer_id == customer_id]

    # --- gated writes ------------------------------------------------------
    def issue_refund(
        self, invoice_id: str, amount_cents: int, *, idempotency_key: str
    ) -> RefundReceipt:
        if idempotency_key in self._refunds:
            return self._refunds[idempotency_key]
        if amount_cents <= 0:
            raise BillingError("refund amount must be positive")
        invoice = self._invoices.get(invoice_id)
        if invoice is None:
            raise BillingError(f"unknown invoice {invoice_id!r}")
        if amount_cents > invoice.refundable_remaining_cents:
            raise BillingError(
                f"refund {amount_cents} exceeds remaining "
                f"{invoice.refundable_remaining_cents} on {invoice_id!r}"
            )
        new_refunded = invoice.refunded_cents + amount_cents
        new_status = (
            InvoiceStatus.REFUNDED if new_refunded >= invoice.amount_cents else invoice.status
        )
        self._invoices[invoice_id] = invoice.model_copy(
            update={"refunded_cents": new_refunded, "status": new_status}
        )
        receipt = RefundReceipt(
            invoice_id=invoice_id,
            amount_cents=amount_cents,
            idempotency_key=idempotency_key,
            refunded_total_cents=new_refunded,
        )
        self._refunds[idempotency_key] = receipt
        return receipt

    def cancel_subscription(self, subscription_id: str, *, idempotency_key: str) -> CancelReceipt:
        if idempotency_key in self._cancels:
            return self._cancels[idempotency_key]
        subscription = self._subscriptions.get(subscription_id)
        if subscription is None:
            raise BillingError(f"unknown subscription {subscription_id!r}")
        self._subscriptions[subscription_id] = subscription.model_copy(
            update={"status": SubscriptionStatus.CANCELED}
        )
        receipt = CancelReceipt(
            subscription_id=subscription_id,
            idempotency_key=idempotency_key,
            status=SubscriptionStatus.CANCELED,
        )
        self._cancels[idempotency_key] = receipt
        return receipt
