"""The grounding gate — the anti-hallucination control.

Where the policy gate asks "is this action *authorized*?", the grounding gate
asks "is this action *supported by records the agent actually retrieved*?" It
rejects a proposal whose cited evidence doesn't exist, belongs to another
customer, or doesn't actually reference the thing being changed. A refund the
brain dreamed up — citing an invoice that isn't in the customer's records — is
caught here before it ever reaches the policy gate or the store.
"""

from __future__ import annotations

import datetime as dt

from relay.actions import AnswerAction, CancelAction, EscalateAction, RefundAction
from relay.domain import Invoice, InvoiceStatus, Subscription, SubscriptionStatus
from relay.grounding import GroundingContext, check_grounding
from relay.proposal import Grounding

UTC = dt.UTC
NOW = dt.datetime(2025, 1, 31, tzinfo=UTC)


def _invoice(invoice_id: str = "in_1", customer_id: str = "cus_1") -> Invoice:
    return Invoice(
        id=invoice_id,
        customer_id=customer_id,
        subscription_id="sub_1",
        amount_cents=2000,
        currency="usd",
        status=InvoiceStatus.PAID,
        created_at=NOW,
    )


def _sub(sub_id: str = "sub_1", customer_id: str = "cus_1") -> Subscription:
    return Subscription(
        id=sub_id,
        customer_id=customer_id,
        plan="pro",
        status=SubscriptionStatus.ACTIVE,
        amount_cents=2000,
        currency="usd",
        current_period_end=NOW,
    )


def _ctx(
    *, invoices: list[Invoice] | None = None, subscriptions: list[Subscription] | None = None
) -> GroundingContext:
    return GroundingContext(
        ticket_customer_id="cus_1",
        invoices=invoices if invoices is not None else [_invoice()],
        subscriptions=subscriptions if subscriptions is not None else [_sub()],
    )


# --- grounded -----------------------------------------------------------------


def test_refund_citing_a_real_owned_invoice_is_grounded() -> None:
    g = Grounding(
        customer_id="cus_1", cited_invoice_ids=["in_1"], evidence="invoice in_1 charged twice"
    )
    res = check_grounding(RefundAction(invoice_id="in_1", amount_cents=2000, reason="x"), g, _ctx())
    assert res.grounded is True
    assert res.code == "ok"


def test_pure_informational_answer_needs_no_citations() -> None:
    g = Grounding(customer_id="cus_1", evidence="general policy question")
    res = check_grounding(AnswerAction(), g, _ctx())
    assert res.grounded is True


def test_escalation_is_always_grounded() -> None:
    g = Grounding(customer_id="cus_999")  # even a bogus claim
    res = check_grounding(EscalateAction(reason="unclear"), g, _ctx())
    assert res.grounded is True


# --- ungrounded ---------------------------------------------------------------


def test_acting_for_a_different_customer_is_rejected() -> None:
    g = Grounding(customer_id="cus_999", cited_invoice_ids=["in_1"], evidence="x")
    res = check_grounding(RefundAction(invoice_id="in_1", amount_cents=2000, reason="x"), g, _ctx())
    assert res.grounded is False
    assert res.code == "customer_mismatch"


def test_citing_a_nonexistent_invoice_is_rejected() -> None:
    g = Grounding(customer_id="cus_1", cited_invoice_ids=["in_ghost"], evidence="x")
    res = check_grounding(AnswerAction(), g, _ctx())
    assert res.grounded is False
    assert res.code == "cited_invoice_not_found"


def test_citing_another_customers_invoice_is_rejected() -> None:
    g = Grounding(customer_id="cus_1", cited_invoice_ids=["in_x"], evidence="x")
    ctx = _ctx(invoices=[_invoice(invoice_id="in_x", customer_id="cus_2")])
    res = check_grounding(AnswerAction(), g, ctx)
    assert res.grounded is False
    assert res.code == "cited_invoice_cross_customer"


def test_refund_target_must_be_cited() -> None:
    # Brain wants to refund in_1 but cited a different invoice as evidence.
    g = Grounding(customer_id="cus_1", cited_invoice_ids=["in_other"], evidence="x")
    ctx = _ctx(invoices=[_invoice(), _invoice(invoice_id="in_other")])
    res = check_grounding(RefundAction(invoice_id="in_1", amount_cents=2000, reason="x"), g, ctx)
    assert res.grounded is False
    assert res.code == "refund_target_not_cited"


def test_refund_with_no_evidence_is_rejected() -> None:
    g = Grounding(customer_id="cus_1", cited_invoice_ids=["in_1"], evidence="   ")
    res = check_grounding(RefundAction(invoice_id="in_1", amount_cents=2000, reason="x"), g, _ctx())
    assert res.grounded is False
    assert res.code == "no_evidence"


def test_cancel_target_must_be_cited() -> None:
    g = Grounding(customer_id="cus_1", cited_subscription_ids=[], evidence="customer asked")
    res = check_grounding(CancelAction(subscription_id="sub_1", reason="x"), g, _ctx())
    assert res.grounded is False
    assert res.code == "cancel_target_not_cited"


def test_citing_a_nonexistent_subscription_is_rejected() -> None:
    g = Grounding(customer_id="cus_1", cited_subscription_ids=["sub_ghost"], evidence="x")
    res = check_grounding(AnswerAction(), g, _ctx())
    assert res.grounded is False
    assert res.code == "cited_subscription_not_found"
