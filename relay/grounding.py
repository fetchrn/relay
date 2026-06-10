"""The grounding gate — verify a proposal is supported by real records.

The grounding gate is the anti-hallucination control. It is independent of the
policy gate:

* policy gate  → "is this action *authorized*?" (caps, window, ownership, confidence)
* grounding gate → "is this action *backed by records the agent actually retrieved*?"

A proposal passes only if the brain's grounding claim checks out against the
retrieved records: it is acting for the right customer, every record it cites
exists and belongs to that customer, and any state-changing action actually
cites the record it intends to change. An invented refund — citing an invoice
that isn't in the customer's account — is rejected here, before policy or the
store ever see it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from relay.actions import CancelAction, EscalateAction, ProposedAction, RefundAction
from relay.domain import Invoice, Subscription
from relay.proposal import Grounding


class GroundingContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_customer_id: str
    invoices: list[Invoice]
    subscriptions: list[Subscription]


class GroundingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    grounded: bool
    code: str
    reason: str


def _ok() -> GroundingResult:
    return GroundingResult(
        grounded=True, code="ok", reason="proposal is grounded in retrieved records"
    )


def _fail(code: str, reason: str) -> GroundingResult:
    return GroundingResult(grounded=False, code=code, reason=reason)


def check_grounding(
    action: ProposedAction, grounding: Grounding, ctx: GroundingContext
) -> GroundingResult:
    """Return whether the proposal's grounding claim holds against the records."""
    # Escalation needs no grounding — handing off to a human is always safe.
    if isinstance(action, EscalateAction):
        return _ok()

    # The agent must be acting for the authenticated customer on the ticket.
    if grounding.customer_id != ctx.ticket_customer_id:
        return _fail(
            "customer_mismatch",
            f"proposal claims customer {grounding.customer_id!r} but the ticket is "
            f"{ctx.ticket_customer_id!r}",
        )

    invoices_by_id = {i.id: i for i in ctx.invoices}
    subs_by_id = {s.id: s for s in ctx.subscriptions}

    # Every cited record must exist and belong to this customer.
    for inv_id in grounding.cited_invoice_ids:
        invoice = invoices_by_id.get(inv_id)
        if invoice is None:
            return _fail(
                "cited_invoice_not_found", f"cited invoice {inv_id!r} is not in the records"
            )
        if invoice.customer_id != ctx.ticket_customer_id:
            return _fail(
                "cited_invoice_cross_customer",
                f"cited invoice {inv_id!r} belongs to another customer",
            )
    for sub_id in grounding.cited_subscription_ids:
        sub = subs_by_id.get(sub_id)
        if sub is None:
            return _fail(
                "cited_subscription_not_found",
                f"cited subscription {sub_id!r} is not in the records",
            )
        if sub.customer_id != ctx.ticket_customer_id:
            return _fail(
                "cited_subscription_cross_customer",
                f"cited subscription {sub_id!r} belongs to another customer",
            )

    # State-changing actions must cite the exact record they intend to change,
    # and offer some evidence for the change.
    if isinstance(action, RefundAction):
        if not grounding.evidence.strip():
            return _fail("no_evidence", "a refund must be backed by stated evidence")
        if action.invoice_id not in grounding.cited_invoice_ids:
            return _fail(
                "refund_target_not_cited",
                f"refund targets invoice {action.invoice_id!r} but it was not cited as evidence",
            )
    elif isinstance(action, CancelAction):
        if not grounding.evidence.strip():
            return _fail("no_evidence", "a cancellation must be backed by stated evidence")
        if action.subscription_id not in grounding.cited_subscription_ids:
            return _fail(
                "cancel_target_not_cited",
                f"cancellation targets {action.subscription_id!r} but it was not cited as evidence",
            )

    return _ok()
