"""The closed set of actions the agent may propose.

This is a *closed* discriminated union on purpose. The brain can only ever
propose one of these four shapes; there is no free-form "do X" escape hatch.
Adding a new capability means adding a new action type here **and** a matching
allow-rule in :mod:`relay.policy` — you cannot widen what the agent can do
without also writing the authorization for it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Action(BaseModel):
    model_config = ConfigDict(frozen=True)


class AnswerAction(_Action):
    """Answer the customer's question. Changes no money or account state."""

    type: Literal["answer"] = "answer"


class RefundAction(_Action):
    """Refund ``amount_cents`` against a specific invoice."""

    type: Literal["refund"] = "refund"
    invoice_id: str
    amount_cents: int
    reason: str


class CancelAction(_Action):
    """Cancel a specific subscription."""

    type: Literal["cancel_subscription"] = "cancel_subscription"
    subscription_id: str
    reason: str


class EscalateAction(_Action):
    """Hand the ticket to a human. Always the safe default."""

    type: Literal["escalate"] = "escalate"
    reason: str


ProposedAction = Annotated[
    AnswerAction | RefundAction | CancelAction | EscalateAction,
    Field(discriminator="type"),
]
