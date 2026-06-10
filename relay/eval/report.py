"""The eval report — a schema-stable, deterministic run artifact.

The report is byte-deterministic given the same brain, world, and injected
timestamp, so the committed snapshot can be regression-checked in CI and the
dashboard can render it as a static asset.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from relay.agent import Outcome
from relay.metrics import Metrics

SCHEMA_VERSION = "run-report-v1"


class CaseRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: str
    expected_outcome: Outcome
    actual_outcome: Outcome
    expected_code: str | None
    actual_code: str
    executed: bool
    unsafe: bool
    correct: bool


class AuditSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    records: int
    verified: bool
    head_hash: str


class EvalReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION
    brain: str
    generated_at: str
    metrics: Metrics
    by_category: dict[str, Metrics]
    cases: list[CaseRow]
    audit: AuditSummary

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        return cls.model_json_schema()

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    def to_markdown(self) -> str:
        m = self.metrics
        lines = [
            f"# Relay eval report ({self.brain})",
            "",
            f"- generated: `{self.generated_at}`",
            f"- cases: **{m.total}**",
            f"- automated resolution rate (correct + autonomous): "
            f"**{m.automated_resolution_rate:.0%}**",
            f"- deflection rate (vanity metric — didn't reach a human): {m.deflection_rate:.0%}",
            f"- escalation rate: {m.escalation_rate:.0%}",
            f"- accuracy (outcome matches label): {m.accuracy:.0%}",
            f"- **unsafe-action rate: {m.unsafe_action_rate:.0%}** "
            f"({m.unsafe}/{m.total} unsafe state changes)",
            f"- audit chain: {self.audit.records} records, "
            f"verified={str(self.audit.verified).lower()}",
            "",
            "| case | category | expected | actual | code | unsafe | correct |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in self.cases:
            lines.append(
                f"| {c.case_id} | {c.category} | {c.expected_outcome} | {c.actual_outcome} "
                f"| {c.actual_code} | {'yes' if c.unsafe else 'no'} "
                f"| {'✓' if c.correct else '✗'} |"
            )
        return "\n".join(lines) + "\n"
