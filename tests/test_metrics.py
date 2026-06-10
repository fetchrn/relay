"""Support-agent metrics — resolution, not deflection.

The headline number is the **automated resolution rate** (the ticket was solved
correctly, autonomously). Deflection (just "didn't reach a human") is reported
too, but it is the vanity metric — it counts wrong auto-answers as wins, so
deflection is always >= automated resolution. The number that gets you fired is
the **unsafe-action rate**, and the whole system is built to keep it at zero.
"""

from __future__ import annotations

from relay.agent import Outcome
from relay.metrics import CaseScore, compute


def _s(
    outcome: Outcome, *, correct: bool, unsafe: bool = False, category: str = "refund"
) -> CaseScore:
    return CaseScore(
        case_id="c",
        category=category,
        expected_outcome=outcome,
        actual_outcome=outcome,
        unsafe=unsafe,
        correct=correct,
    )


def test_empty_suite_is_all_zero_no_division_error() -> None:
    m = compute([])
    assert m.total == 0
    assert m.resolution_rate == 0.0
    assert m.unsafe_action_rate == 0.0


def test_rates_are_computed() -> None:
    scores = [
        _s(Outcome.RESOLVED, correct=True),
        _s(Outcome.RESOLVED, correct=True),
        _s(Outcome.ESCALATED, correct=True),
        _s(Outcome.ESCALATED, correct=True),
    ]
    m = compute(scores)
    assert m.total == 4
    assert m.resolved == 2
    assert m.escalated == 2
    assert m.resolution_rate == 0.5
    assert m.escalation_rate == 0.5
    assert m.automated_resolution_rate == 0.5
    assert m.unsafe_action_rate == 0.0


def test_deflection_is_at_least_automated_resolution() -> None:
    # A wrong auto-answer: resolved (no human) but not correct.
    scores = [
        CaseScore(
            case_id="c1",
            category="question",
            expected_outcome=Outcome.ESCALATED,
            actual_outcome=Outcome.RESOLVED,
            unsafe=False,
            correct=False,
        ),
        _s(Outcome.RESOLVED, correct=True),
    ]
    m = compute(scores)
    assert m.deflection_rate == 1.0  # both resolved (neither reached a human)
    assert m.automated_resolution_rate == 0.5  # only one was actually correct
    assert m.deflection_rate >= m.automated_resolution_rate


def test_unsafe_action_rate_counts_executed_unsafe_changes() -> None:
    scores = [
        CaseScore(
            case_id="bad",
            category="adversarial",
            expected_outcome=Outcome.ESCALATED,
            actual_outcome=Outcome.RESOLVED,
            unsafe=True,
            correct=False,
        ),
        _s(Outcome.ESCALATED, correct=True),
    ]
    m = compute(scores)
    assert m.unsafe == 1
    assert m.unsafe_action_rate == 0.5
