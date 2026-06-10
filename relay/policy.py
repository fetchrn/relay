"""The fail-closed action policy gate — Relay's safety core.

`decide(action, ctx)` is a pure, deterministic, **deny-by-default** function.
It begins from "not authorized" and only returns :attr:`Verdict.ALLOW` when a
specific allow-rule matches and no deny-rule fires. There is deliberately no
``else: allow`` in this module: every code path that is not an explicit,
fully-checked allow returns :attr:`Verdict.ESCALATE`.

The gate does not trust the brain. The brain proposes an action and asserts its
own grounding; the gate independently re-checks every load-bearing fact —
ownership, amount, refund window, invoice status, confidence, topic sensitivity
— against the real records in :class:`PolicyContext`. "The model said so" is
never an authorization.

The brain only ever *requests* a refund within policy; the cap, window, and
ownership checks are enforced here in code, where no amount of prompt injection
in a ticket can reach them.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from relay.actions import (
    AnswerAction,
    CancelAction,
    EscalateAction,
    ProposedAction,
    RefundAction,
)
from relay.domain import Customer, Invoice, InvoiceStatus, Subscription, Ticket


class Verdict(StrEnum):
    ALLOW = "allow"  # safe to auto-execute
    ESCALATE = "escalate"  # route to a human; never auto-execute


class PolicyConfig(BaseModel):
    """The explicit, tunable policy. Every limit a reviewer cares about is here,
    in one auditable object — not scattered through prompts."""

    model_config = ConfigDict(frozen=True)

    max_refund_cents: int = 5000
    refund_window_days: int = 30
    min_confidence: float = 0.7
    allow_auto_refund: bool = True
    allow_auto_cancel: bool = True
    sensitive_topics_escalate: bool = True


class PolicyContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket: Ticket
    customer: Customer
    subscriptions: list[Subscription]
    invoices: list[Invoice]
    confidence: float
    sensitive_topic: bool
    now: dt.datetime
    config: PolicyConfig = Field(default_factory=PolicyConfig)


class GateDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: Verdict
    code: str
    reason: str


def _escalate(code: str, reason: str) -> GateDecision:
    return GateDecision(verdict=Verdict.ESCALATE, code=code, reason=reason)


def _allow(code: str, reason: str) -> GateDecision:
    return GateDecision(verdict=Verdict.ALLOW, code=code, reason=reason)


def _find_invoice(invoices: list[Invoice], invoice_id: str) -> Invoice | None:
    return next((i for i in invoices if i.id == invoice_id), None)


def _find_subscription(subs: list[Subscription], sub_id: str) -> Subscription | None:
    return next((s for s in subs if s.id == sub_id), None)


def decide(action: ProposedAction, ctx: PolicyContext) -> GateDecision:
    """Authorize (or refuse) a proposed action. Deny-by-default."""
    # Escalation is always the safe action — a human will look at it.
    if isinstance(action, EscalateAction):
        return _allow("escalate_requested", "agent requested human handoff")

    # Global guards applied to every non-escalate action.
    if ctx.config.sensitive_topics_escalate and ctx.sensitive_topic:
        return _escalate(
            "sensitive_topic",
            "ticket touches a sensitive topic (financial/medical advice, distress, dispute); "
            "a human must handle it",
        )
    if ctx.confidence < ctx.config.min_confidence:
        return _escalate(
            "low_confidence",
            f"confidence {ctx.confidence:.2f} below threshold {ctx.config.min_confidence:.2f}",
        )

    if isinstance(action, AnswerAction):
        return _allow("answer_ok", "informational reply within confidence threshold")

    if isinstance(action, RefundAction):
        return _decide_refund(action, ctx)

    if isinstance(action, CancelAction):
        return _decide_cancel(action, ctx)

    # Defensive default. The union above is closed, so this is unreachable for
    # known actions — but if a new action type is ever added without an
    # allow-rule, it escalates rather than silently passing. No else: allow.
    return _escalate("unknown_action", "no allow-rule matched this action")


def _decide_refund(action: RefundAction, ctx: PolicyContext) -> GateDecision:
    if not ctx.config.allow_auto_refund:
        return _escalate("auto_refund_disabled", "automatic refunds are turned off by policy")
    if action.amount_cents <= 0:
        return _escalate("non_positive_amount", "refund amount must be positive")

    invoice = _find_invoice(ctx.invoices, action.invoice_id)
    if invoice is None:
        return _escalate(
            "unknown_invoice", f"invoice {action.invoice_id!r} not in this customer's records"
        )
    if invoice.customer_id != ctx.customer.id:
        return _escalate(
            "cross_customer",
            f"invoice {action.invoice_id!r} is on another customer's account; refusing",
        )
    if invoice.status is not InvoiceStatus.PAID:
        return _escalate(
            "invoice_not_refundable", f"invoice {action.invoice_id!r} is {invoice.status}, not paid"
        )
    if action.amount_cents > ctx.config.max_refund_cents:
        return _escalate(
            "refund_exceeds_cap",
            f"refund {action.amount_cents} over the auto-refund cap {ctx.config.max_refund_cents}",
        )
    if action.amount_cents > invoice.refundable_remaining_cents:
        return _escalate(
            "refund_exceeds_remaining",
            f"refund {action.amount_cents} exceeds remaining refundable "
            f"{invoice.refundable_remaining_cents} on {action.invoice_id!r}",
        )
    age_days = (ctx.now - invoice.created_at).days
    if age_days > ctx.config.refund_window_days:
        return _escalate(
            "refund_outside_window",
            f"invoice {age_days}d old, past the {ctx.config.refund_window_days}d refund window",
        )
    return _allow("refund_ok", "refund is within cap, window, remaining balance, and ownership")


def _decide_cancel(action: CancelAction, ctx: PolicyContext) -> GateDecision:
    if not ctx.config.allow_auto_cancel:
        return _escalate("auto_cancel_disabled", "automatic cancellations are turned off by policy")

    sub = _find_subscription(ctx.subscriptions, action.subscription_id)
    if sub is None:
        return _escalate(
            "unknown_subscription",
            f"subscription {action.subscription_id!r} not in this customer's records",
        )
    if sub.customer_id != ctx.customer.id:
        return _escalate(
            "cross_customer",
            f"subscription {action.subscription_id!r} belongs to a different customer",
        )
    if not sub.is_active:
        return _escalate(
            "subscription_not_active", f"subscription {action.subscription_id!r} is {sub.status}"
        )
    return _allow("cancel_ok", "subscription is active and owned by this customer")
