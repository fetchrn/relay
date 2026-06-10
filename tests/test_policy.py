"""The fail-closed action policy gate — the safety core.

`decide()` is deterministic, pure, and **deny-by-default**: it begins from "not
authorized" and only returns ALLOW when a specific allow-rule matches and no
deny-rule fires. There is no ``else: allow`` anywhere in it. Every path that
isn't an explicit, fully-checked allow falls through to ESCALATE.

Crucially, the gate does **not** trust the brain's claims. The brain proposes an
action and asserts its own grounding; the gate re-checks every fact (ownership,
amount, window, status, confidence, sensitivity) against the real records passed
in the context. "The model said it was fine" is never an authorization.
"""

from __future__ import annotations

import datetime as dt

from relay.actions import AnswerAction, CancelAction, EscalateAction, RefundAction
from relay.domain import (
    Channel,
    Customer,
    Invoice,
    InvoiceStatus,
    Subscription,
    SubscriptionStatus,
    Ticket,
)
from relay.policy import PolicyConfig, PolicyContext, Verdict, decide

UTC = dt.UTC
NOW = dt.datetime(2025, 1, 31, tzinfo=UTC)


def _ctx(
    *,
    invoices: list[Invoice] | None = None,
    subscriptions: list[Subscription] | None = None,
    confidence: float = 0.95,
    sensitive_topic: bool = False,
    config: PolicyConfig | None = None,
) -> PolicyContext:
    customer = Customer(
        id="cus_1",
        email="ada@example.com",
        name="Ada",
        created_at=dt.datetime(2025, 1, 1, tzinfo=UTC),
    )
    ticket = Ticket(
        id="tkt_1",
        customer_id="cus_1",
        subject="help",
        body="please help",
        channel=Channel.EMAIL,
        created_at=NOW,
    )
    return PolicyContext(
        ticket=ticket,
        customer=customer,
        subscriptions=subscriptions or [],
        invoices=invoices or [],
        confidence=confidence,
        sensitive_topic=sensitive_topic,
        now=NOW,
        config=config or PolicyConfig(),
    )


def _paid_invoice(
    *,
    invoice_id: str = "in_1",
    customer_id: str = "cus_1",
    amount: int = 2000,
    refunded: int = 0,
    age_days: int = 5,
    status: InvoiceStatus = InvoiceStatus.PAID,
) -> Invoice:
    return Invoice(
        id=invoice_id,
        customer_id=customer_id,
        subscription_id="sub_1",
        amount_cents=amount,
        currency="usd",
        status=status,
        created_at=NOW - dt.timedelta(days=age_days),
        refunded_cents=refunded,
    )


def _active_sub(
    *,
    sub_id: str = "sub_1",
    customer_id: str = "cus_1",
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
) -> Subscription:
    return Subscription(
        id=sub_id,
        customer_id=customer_id,
        plan="pro",
        status=status,
        amount_cents=2000,
        currency="usd",
        current_period_end=NOW + dt.timedelta(days=10),
    )


# --- ALLOW paths ------------------------------------------------------------


def test_grounded_confident_answer_is_allowed() -> None:
    d = decide(AnswerAction(), _ctx())
    assert d.verdict is Verdict.ALLOW


def test_in_policy_refund_is_allowed() -> None:
    d = decide(
        RefundAction(invoice_id="in_1", amount_cents=2000, reason="double charge"),
        _ctx(invoices=[_paid_invoice()]),
    )
    assert d.verdict is Verdict.ALLOW


def test_cancel_active_owned_subscription_is_allowed() -> None:
    d = decide(
        CancelAction(subscription_id="sub_1", reason="no longer needed"),
        _ctx(subscriptions=[_active_sub()]),
    )
    assert d.verdict is Verdict.ALLOW


def test_escalate_action_is_always_safe() -> None:
    d = decide(
        EscalateAction(reason="customer is upset"), _ctx(confidence=0.0, sensitive_topic=True)
    )
    assert d.verdict is Verdict.ALLOW


# --- ESCALATE paths (the fail-closed behavior) ------------------------------


def test_low_confidence_escalates() -> None:
    d = decide(AnswerAction(), _ctx(confidence=0.4))
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "low_confidence"


def test_sensitive_topic_escalates_even_when_confident() -> None:
    d = decide(AnswerAction(), _ctx(confidence=0.99, sensitive_topic=True))
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "sensitive_topic"


def test_refund_over_cap_escalates() -> None:
    d = decide(
        RefundAction(invoice_id="in_1", amount_cents=4000, reason="x"),
        _ctx(invoices=[_paid_invoice(amount=10000)], config=PolicyConfig(max_refund_cents=3000)),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "refund_exceeds_cap"


def test_refund_over_remaining_escalates() -> None:
    d = decide(
        RefundAction(invoice_id="in_1", amount_cents=2000, reason="x"),
        _ctx(invoices=[_paid_invoice(amount=2000, refunded=1500)]),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "refund_exceeds_remaining"


def test_refund_outside_window_escalates() -> None:
    d = decide(
        RefundAction(invoice_id="in_1", amount_cents=1000, reason="x"),
        _ctx(invoices=[_paid_invoice(age_days=90)], config=PolicyConfig(refund_window_days=30)),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "refund_outside_window"


def test_refund_on_unpaid_invoice_escalates() -> None:
    d = decide(
        RefundAction(invoice_id="in_1", amount_cents=1000, reason="x"),
        _ctx(invoices=[_paid_invoice(status=InvoiceStatus.OPEN)]),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "invoice_not_refundable"


def test_refund_for_unknown_invoice_escalates() -> None:
    d = decide(
        RefundAction(invoice_id="in_ghost", amount_cents=1000, reason="x"),
        _ctx(invoices=[_paid_invoice()]),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "unknown_invoice"


def test_refund_for_another_customers_invoice_escalates() -> None:
    # The cited invoice exists in context but belongs to a different customer.
    # This is the cross-customer data-leak failure mode — must never auto-execute.
    d = decide(
        RefundAction(invoice_id="in_other", amount_cents=1000, reason="x"),
        _ctx(invoices=[_paid_invoice(invoice_id="in_other", customer_id="cus_999")]),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "cross_customer"


def test_zero_or_negative_refund_escalates() -> None:
    d = decide(
        RefundAction(invoice_id="in_1", amount_cents=0, reason="x"),
        _ctx(invoices=[_paid_invoice()]),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "non_positive_amount"


def test_auto_refund_disabled_escalates() -> None:
    d = decide(
        RefundAction(invoice_id="in_1", amount_cents=1000, reason="x"),
        _ctx(invoices=[_paid_invoice()], config=PolicyConfig(allow_auto_refund=False)),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "auto_refund_disabled"


def test_cancel_other_customers_subscription_escalates() -> None:
    d = decide(
        CancelAction(subscription_id="sub_x", reason="x"),
        _ctx(subscriptions=[_active_sub(sub_id="sub_x", customer_id="cus_999")]),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "cross_customer"


def test_cancel_unknown_subscription_escalates() -> None:
    d = decide(
        CancelAction(subscription_id="sub_ghost", reason="x"),
        _ctx(subscriptions=[_active_sub()]),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "unknown_subscription"


def test_cancel_already_canceled_subscription_escalates() -> None:
    d = decide(
        CancelAction(subscription_id="sub_1", reason="x"),
        _ctx(subscriptions=[_active_sub(status=SubscriptionStatus.CANCELED)]),
    )
    assert d.verdict is Verdict.ESCALATE
    assert d.code == "subscription_not_active"


# --- The by-construction guarantee ------------------------------------------


def test_refund_never_exceeds_cap_across_a_wide_range() -> None:
    """Property check: for any amount above the cap, the gate refuses. There is
    no amount, however framed, that makes an over-cap refund auto-execute."""
    config = PolicyConfig(max_refund_cents=5000)
    invoice = _paid_invoice(amount=1_000_000)  # plenty of headroom on the invoice
    for amount in range(5001, 20001, 250):
        d = decide(
            RefundAction(invoice_id="in_1", amount_cents=amount, reason="x"),
            _ctx(invoices=[invoice], config=config),
        )
        assert d.verdict is Verdict.ESCALATE, f"amount {amount} should not auto-execute"


def test_every_escalation_carries_a_machine_readable_code_and_reason() -> None:
    d = decide(AnswerAction(), _ctx(confidence=0.1))
    assert d.code
    assert d.reason
    assert d.verdict is Verdict.ESCALATE
