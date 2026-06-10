"""Immutable domain value objects for billing and support tickets.

These are pure data. No eligibility rules, caps, or authorization logic live
here — that is the policy gate's job (see :mod:`relay.policy`). Keeping the
domain dumb is deliberate: a record can't grant permission, so there is no path
by which "the data said it was fine" becomes an authorization.

Money is always integer cents with an explicit currency. Floats never touch
money.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    """Base for immutable, validated value objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Channel(StrEnum):
    EMAIL = "email"
    CHAT = "chat"
    PHONE = "phone"
    API = "api"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    TRIALING = "trialing"


class InvoiceStatus(StrEnum):
    PAID = "paid"
    OPEN = "open"
    REFUNDED = "refunded"
    UNCOLLECTIBLE = "uncollectible"


class Customer(_Frozen):
    id: str
    email: str
    name: str
    created_at: dt.datetime


class Subscription(_Frozen):
    id: str
    customer_id: str
    plan: str
    status: SubscriptionStatus
    amount_cents: int = Field(ge=0)
    currency: str
    current_period_end: dt.datetime

    @property
    def is_active(self) -> bool:
        return self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING)


class Invoice(_Frozen):
    id: str
    customer_id: str
    subscription_id: str | None
    amount_cents: int = Field(ge=0)
    currency: str
    status: InvoiceStatus
    created_at: dt.datetime
    refunded_cents: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _refund_cannot_exceed_amount(self) -> Invoice:
        if self.refunded_cents > self.amount_cents:
            raise ValueError("refunded_cents cannot exceed amount_cents")
        return self

    @property
    def refundable_remaining_cents(self) -> int:
        return self.amount_cents - self.refunded_cents


class Ticket(_Frozen):
    id: str
    customer_id: str
    subject: str
    body: str
    channel: Channel
    created_at: dt.datetime


def dollars(cents: int) -> str:
    """Render integer cents as a human-readable USD-style string.

    Display helper only — never use the float for arithmetic.
    """
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
