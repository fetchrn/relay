"""The brain's structured proposal.

This is the schema the LLM is constrained to produce (via Claude structured
outputs). It is shared by the brain (which fills it), the grounding gate (which
checks the ``grounding`` claim), and the orchestrator (which derives policy
context from ``confidence`` and ``sensitive_topic``).

Keeping it in its own module keeps the LLM layer and the safety gates from
importing each other.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from relay.actions import ProposedAction


class Intent(StrEnum):
    BILLING_QUESTION = "billing_question"
    REFUND_REQUEST = "refund_request"
    CANCELLATION = "cancellation"
    ACCOUNT_QUESTION = "account_question"
    COMPLAINT = "complaint"
    OTHER = "other"


class Grounding(BaseModel):
    """The brain's claim about what records justify its proposal.

    The grounding gate verifies every field of this against the records actually
    retrieved — it is a claim to be checked, never trusted.
    """

    model_config = ConfigDict(frozen=True)

    customer_id: str
    cited_invoice_ids: list[str] = Field(default_factory=list)
    cited_subscription_ids: list[str] = Field(default_factory=list)
    evidence: str = ""


class AgentProposal(BaseModel):
    """The complete, structured output of one brain turn."""

    model_config = ConfigDict(frozen=True)

    intent: Intent
    action: ProposedAction
    confidence: float = Field(ge=0.0, le=1.0)
    sensitive_topic: bool
    grounding: Grounding
    customer_reply: str
    rationale: str
