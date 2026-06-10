"""The orchestrator — handle one ticket, end to end.

The pipeline is fixed and the order matters:

    intake → retrieve (scoped) → propose → ground → gate → execute | escalate
           → audit → respond

* **Retrieve is scoped to the ticket's customer.** The brain only ever sees that
  customer's records, so it cannot accidentally act across accounts.
* **The brain proposes; it never executes.** Only this module calls the store,
  and only after both the grounding gate and the policy gate allow.
* **Failure is escalation.** Unknown customer, ungrounded proposal, policy block,
  or a store rejection all converge on the same safe outcome: a human gets a case
  file, and no money or account state changes.

Every step is an OpenTelemetry span, so a run is observable in any OTLP backend.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from relay.actions import (
    AnswerAction,
    CancelAction,
    EscalateAction,
    ProposedAction,
    RefundAction,
)
from relay.audit import AuditLog, redact
from relay.brain import Brain
from relay.domain import Ticket
from relay.grounding import GroundingContext, GroundingResult, check_grounding
from relay.observability import current_trace_id, get_tracer
from relay.policy import GateDecision, PolicyConfig, PolicyContext, Verdict, decide
from relay.proposal import AgentProposal, Intent
from relay.store import BillingError, BillingStore

_ESCALATION_REPLY = (
    "Thanks for reaching out — I'm connecting you with a teammate who can help with this."
)


class Outcome(StrEnum):
    RESOLVED = "resolved"  # handled end-to-end, no human needed
    ESCALATED = "escalated"  # routed to a human


class CaseFile(BaseModel):
    """The handoff packet a human receives on escalation — evidence, not a cold dump."""

    model_config = ConfigDict(frozen=True)

    ticket_id: str
    customer_id: str
    reason: str
    gate_code: str
    proposed_action_type: str
    grounding_summary: str
    evidence: str
    suggested_resolution: str


class TicketResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    customer_id: str
    outcome: Outcome
    intent: Intent
    action_type: str
    customer_reply: str
    gate_code: str  # the controlling code (the reason for the outcome)
    grounding_code: str
    policy_code: str
    confidence: float
    executed: bool
    receipt: dict[str, str] | None
    case_file: CaseFile | None
    audit_seq: int
    trace_id: str | None


class Agent:
    """Wires the brain, the two gates, the store, and the audit log together."""

    def __init__(
        self,
        *,
        brain: Brain,
        store: BillingStore,
        config: PolicyConfig | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.brain = brain
        self.store = store
        self.config = config or PolicyConfig()
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self.audit = AuditLog()

    def handle(self, ticket: Ticket) -> TicketResolution:
        tracer = get_tracer()
        with tracer.start_as_current_span("relay.handle_ticket") as span:
            span.set_attribute("ticket.id", ticket.id)
            span.set_attribute("customer.id", ticket.customer_id)
            trace_id = current_trace_id()
            now = self._clock()

            customer = self.store.get_customer(ticket.customer_id)
            if customer is None:
                return self._escalate_unknown_customer(ticket, now, trace_id)

            subs = self.store.get_subscriptions(ticket.customer_id)
            invoices = self.store.get_invoices(ticket.customer_id)

            with tracer.start_as_current_span("relay.brain.propose"):
                proposal = self.brain.propose(ticket, customer, subs, invoices)
            span.set_attribute("intent", proposal.intent)
            span.set_attribute("action", proposal.action.type)

            with tracer.start_as_current_span("relay.grounding"):
                gctx = GroundingContext(
                    ticket_customer_id=ticket.customer_id, invoices=invoices, subscriptions=subs
                )
                gres = check_grounding(proposal.action, proposal.grounding, gctx)

            with tracer.start_as_current_span("relay.policy"):
                pctx = PolicyContext(
                    ticket=ticket,
                    customer=customer,
                    subscriptions=subs,
                    invoices=invoices,
                    confidence=proposal.confidence,
                    sensitive_topic=proposal.sensitive_topic,
                    now=now,
                    config=self.config,
                )
                gate = decide(proposal.action, pctx)

            return self._resolve(ticket, proposal, gres, gate, now, trace_id, tracer)

    # --- decision -----------------------------------------------------------
    def _resolve(
        self,
        ticket: Ticket,
        proposal: AgentProposal,
        gres: GroundingResult,
        gate: GateDecision,
        now: dt.datetime,
        trace_id: str | None,
        tracer: object,
    ) -> TicketResolution:
        action = proposal.action

        if isinstance(action, EscalateAction):
            return self._finish_escalated(
                ticket, proposal, gres, gate, "agent_escalated", action.reason, now, trace_id
            )
        if not gres.grounded:
            return self._finish_escalated(
                ticket, proposal, gres, gate, gres.code, gres.reason, now, trace_id
            )
        if gate.verdict is not Verdict.ALLOW:
            return self._finish_escalated(
                ticket, proposal, gres, gate, gate.code, gate.reason, now, trace_id
            )

        with get_tracer().start_as_current_span("relay.execute"):
            try:
                executed, receipt = self._execute(ticket, action)
            except BillingError as exc:
                return self._finish_escalated(
                    ticket, proposal, gres, gate, "store_rejected", str(exc), now, trace_id
                )
        return self._finish_resolved(ticket, proposal, gres, gate, executed, receipt, now, trace_id)

    def _execute(
        self, ticket: Ticket, action: ProposedAction
    ) -> tuple[bool, dict[str, str] | None]:
        if isinstance(action, AnswerAction):
            return False, None
        if isinstance(action, RefundAction):
            refund = self.store.issue_refund(
                action.invoice_id, action.amount_cents, idempotency_key=f"{ticket.id}:refund"
            )
            return True, {
                "invoice_id": refund.invoice_id,
                "amount_cents": str(refund.amount_cents),
                "refunded_total_cents": str(refund.refunded_total_cents),
            }
        if isinstance(action, CancelAction):
            cancel = self.store.cancel_subscription(
                action.subscription_id, idempotency_key=f"{ticket.id}:cancel"
            )
            return True, {
                "subscription_id": cancel.subscription_id,
                "status": cancel.status.value,
            }
        return False, None  # unreachable: closed union, no else: allow

    # --- terminal builders --------------------------------------------------
    def _finish_resolved(
        self,
        ticket: Ticket,
        proposal: AgentProposal,
        gres: GroundingResult,
        gate: GateDecision,
        executed: bool,
        receipt: dict[str, str] | None,
        now: dt.datetime,
        trace_id: str | None,
    ) -> TicketResolution:
        detail = self._detail(proposal, gres, gate, "resolved", receipt)
        record = self.audit.append(
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            kind="resolved",
            action_type=proposal.action.type,
            verdict=gate.verdict.value,
            code=gate.code,
            grounded=gres.grounded,
            detail=detail,
            timestamp=now.isoformat(),
        )
        return TicketResolution(
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            outcome=Outcome.RESOLVED,
            intent=proposal.intent,
            action_type=proposal.action.type,
            customer_reply=proposal.customer_reply,
            gate_code=gate.code,
            grounding_code=gres.code,
            policy_code=gate.code,
            confidence=proposal.confidence,
            executed=executed,
            receipt=receipt,
            case_file=None,
            audit_seq=record.seq,
            trace_id=trace_id,
        )

    def _finish_escalated(
        self,
        ticket: Ticket,
        proposal: AgentProposal,
        gres: GroundingResult,
        gate: GateDecision,
        code: str,
        reason: str,
        now: dt.datetime,
        trace_id: str | None,
    ) -> TicketResolution:
        case_file = CaseFile(
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            reason=reason,
            gate_code=code,
            proposed_action_type=proposal.action.type,
            grounding_summary=f"{gres.code}: {gres.reason}",
            evidence=proposal.grounding.evidence or "(none provided)",
            suggested_resolution=proposal.customer_reply or "(no draft)",
        )
        detail = self._detail(proposal, gres, gate, "escalated", None)
        detail["code"] = code  # the controlling code wins in the audit
        record = self.audit.append(
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            kind="escalated",
            action_type=proposal.action.type,
            verdict="escalate",
            code=code,
            grounded=gres.grounded,
            detail=detail,
            timestamp=now.isoformat(),
        )
        return TicketResolution(
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            outcome=Outcome.ESCALATED,
            intent=proposal.intent,
            action_type=proposal.action.type,
            customer_reply=_ESCALATION_REPLY,
            gate_code=code,
            grounding_code=gres.code,
            policy_code=gate.code,
            confidence=proposal.confidence,
            executed=False,
            receipt=None,
            case_file=case_file,
            audit_seq=record.seq,
            trace_id=trace_id,
        )

    def _escalate_unknown_customer(
        self, ticket: Ticket, now: dt.datetime, trace_id: str | None
    ) -> TicketResolution:
        case_file = CaseFile(
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            reason=f"no customer record for {ticket.customer_id!r}",
            gate_code="unknown_customer",
            proposed_action_type="escalate",
            grounding_summary="n/a: no records to ground against",
            evidence="(no records — unknown customer)",
            suggested_resolution="Verify the customer's identity, then route appropriately.",
        )
        record = self.audit.append(
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            kind="escalated",
            action_type="escalate",
            verdict="escalate",
            code="unknown_customer",
            grounded=False,
            detail=redact({"code": "unknown_customer", "action": "escalate"}),
            timestamp=now.isoformat(),
        )
        return TicketResolution(
            ticket_id=ticket.id,
            customer_id=ticket.customer_id,
            outcome=Outcome.ESCALATED,
            intent=Intent.OTHER,
            action_type="escalate",
            customer_reply=_ESCALATION_REPLY,
            gate_code="unknown_customer",
            grounding_code="n/a",
            policy_code="n/a",
            confidence=0.0,
            executed=False,
            receipt=None,
            case_file=case_file,
            audit_seq=record.seq,
            trace_id=trace_id,
        )

    @staticmethod
    def _detail(
        proposal: AgentProposal,
        gres: GroundingResult,
        gate: GateDecision,
        resolution: str,
        receipt: dict[str, str] | None,
    ) -> dict[str, str]:
        raw: dict[str, object] = {
            "action": proposal.action.type,
            "intent": proposal.intent.value,
            "verdict": gate.verdict.value,
            "code": gate.code,
            "grounding_code": gres.code,
            "grounded": gres.grounded,
            "confidence": round(proposal.confidence, 2),
            "resolution": resolution,
        }
        if isinstance(proposal.action, RefundAction):
            raw["invoice_id"] = proposal.action.invoice_id
            raw["amount_cents"] = proposal.action.amount_cents
        elif isinstance(proposal.action, CancelAction):
            raw["subscription_id"] = proposal.action.subscription_id
        return redact(raw)
