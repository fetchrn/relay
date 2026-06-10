"""The Stripe billing adapter, exercised offline with a fake client.

The adapter implements the same BillingStore protocol as the in-memory store, so
the orchestrator and gates are unchanged when pointed at real Stripe data. Here
we verify the object mapping and that writes pass through an idempotency key —
without touching the network.
"""

from __future__ import annotations

from typing import Any

from relay.domain import InvoiceStatus, SubscriptionStatus
from relay.store import BillingStore
from relay.stripe_store import StripeBillingStore

NOW_TS = 1738368000  # 2025-02-01T00:00:00Z


class _FakeStripe:
    def __init__(self) -> None:
        self.refund_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[str] = []

        self.Customer = _Resource(
            {"cus_1": {"id": "cus_1", "email": "ada@example.com", "name": "Ada", "created": NOW_TS}}
        )
        self.Subscription = _SubResource(
            {
                "sub_1": {
                    "id": "sub_1",
                    "customer": "cus_1",
                    "status": "active",
                    "plan": "pro",
                    "amount_cents": 2000,
                    "current_period_end": NOW_TS,
                }
            },
            self.cancel_calls,
        )
        self.Invoice = _ListResource(
            [
                {
                    "id": "in_1",
                    "customer": "cus_1",
                    "subscription": "sub_1",
                    "amount_due": 2000,
                    "amount_refunded": 0,
                    "status": "paid",
                    "created": NOW_TS,
                    "charge": "ch_1",
                },
                {
                    "id": "in_2",
                    "customer": "cus_2",
                    "subscription": None,
                    "amount_due": 999,
                    "amount_refunded": 0,
                    "status": "open",
                    "created": NOW_TS,
                    "charge": "ch_2",
                },
            ]
        )
        self.Refund = _RefundResource(self.refund_calls)


class _Resource:
    def __init__(self, by_id: dict[str, dict[str, Any]]) -> None:
        self._by_id = by_id

    def retrieve(self, oid: str) -> dict[str, Any]:
        if oid not in self._by_id:
            raise KeyError(oid)
        return self._by_id[oid]


class _SubResource(_Resource):
    def __init__(self, by_id: dict[str, dict[str, Any]], cancel_calls: list[str]) -> None:
        super().__init__(by_id)
        self._cancel_calls = cancel_calls

    def list(self, customer: str) -> dict[str, Any]:
        return {"data": [s for s in self._by_id.values() if s["customer"] == customer]}

    def delete(self, sub_id: str) -> dict[str, Any]:
        self._cancel_calls.append(sub_id)
        return {**self._by_id[sub_id], "status": "canceled"}


class _ListResource:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def list(self, customer: str) -> dict[str, Any]:
        return {"data": [r for r in self._rows if r["customer"] == customer]}

    def retrieve(self, oid: str) -> dict[str, Any]:
        for r in self._rows:
            if r["id"] == oid:
                return r
        raise KeyError(oid)


class _RefundResource:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self._calls = calls

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self._calls.append(kwargs)
        return {"id": "re_1", "amount": kwargs["amount"]}


def _store() -> StripeBillingStore:
    return StripeBillingStore(client=_FakeStripe())


def test_is_a_billing_store() -> None:
    assert isinstance(_store(), BillingStore)


def test_get_customer_maps_fields() -> None:
    c = _store().get_customer("cus_1")
    assert c is not None
    assert c.email == "ada@example.com"
    assert c.name == "Ada"


def test_unknown_customer_returns_none() -> None:
    assert _store().get_customer("cus_missing") is None


def test_invoices_map_and_scope_to_customer() -> None:
    invs = _store().get_invoices("cus_1")
    assert {i.id for i in invs} == {"in_1"}
    assert invs[0].status is InvoiceStatus.PAID
    assert invs[0].amount_cents == 2000


def test_subscription_maps_status() -> None:
    s = _store().get_subscription("sub_1")
    assert s is not None
    assert s.status is SubscriptionStatus.ACTIVE


def test_issue_refund_passes_amount_and_idempotency_key() -> None:
    store = _store()
    fake = store.client  # type: ignore[attr-defined]
    receipt = store.issue_refund("in_1", 2000, idempotency_key="k1")
    assert receipt.amount_cents == 2000
    call = fake.refund_calls[0]
    assert call["amount"] == 2000
    assert call["idempotency_key"] == "k1"
    assert call["charge"] == "ch_1"


def test_cancel_subscription_calls_delete() -> None:
    store = _store()
    fake = store.client  # type: ignore[attr-defined]
    receipt = store.cancel_subscription("sub_1", idempotency_key="c1")
    assert receipt.status is SubscriptionStatus.CANCELED
    assert fake.cancel_calls == ["sub_1"]
