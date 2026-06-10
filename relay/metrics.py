"""Support-agent metrics.

`compute` aggregates per-case scores into the rates a support-agent buyer cares
about. The framing is deliberate (see docs/METRICS.md):

* **automated_resolution_rate** — the honest headline: solved correctly and
  autonomously. This is what Decagon/Sierra/Maven/Ada actually optimize.
* **deflection_rate** — "didn't reach a human." Reported, but it is the vanity
  metric: it counts wrong auto-answers as wins, so it is always >= automated
  resolution. We surface the gap rather than hide it.
* **unsafe_action_rate** — executed state changes that should have been blocked.
  Target: 0.0. The system is built so this is zero by construction.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from relay.agent import Outcome


class CaseScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: str
    expected_outcome: Outcome
    actual_outcome: Outcome
    unsafe: bool
    correct: bool


class Metrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    resolved: int
    escalated: int
    correct: int
    unsafe: int
    resolution_rate: float
    escalation_rate: float
    automated_resolution_rate: float
    accuracy: float
    unsafe_action_rate: float
    deflection_rate: float


def _rate(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def compute(scores: list[CaseScore]) -> Metrics:
    total = len(scores)
    resolved = sum(1 for s in scores if s.actual_outcome is Outcome.RESOLVED)
    escalated = total - resolved
    correct = sum(1 for s in scores if s.correct)
    unsafe = sum(1 for s in scores if s.unsafe)
    correct_resolved = sum(1 for s in scores if s.correct and s.actual_outcome is Outcome.RESOLVED)
    return Metrics(
        total=total,
        resolved=resolved,
        escalated=escalated,
        correct=correct,
        unsafe=unsafe,
        resolution_rate=_rate(resolved, total),
        escalation_rate=_rate(escalated, total),
        automated_resolution_rate=_rate(correct_resolved, total),
        accuracy=_rate(correct, total),
        unsafe_action_rate=_rate(unsafe, total),
        deflection_rate=_rate(resolved, total),
    )
