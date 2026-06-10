"""Hash-chained, deny-by-default-redacted audit log.

Every decision the agent makes — every resolved ticket, every escalation, every
gate block — is appended here. The log is:

* **Append-only and hash-chained.** Each record's ``hash`` covers its own fields
  plus the previous record's hash. Altering or dropping any record breaks the
  chain, which ``verify_chain`` detects.
* **Deny-by-default redacted.** Records never carry raw PII. The :func:`redact`
  helper keeps only an explicit allowlist of safe, non-identifying fields
  (amounts, record ids, gate codes) and stringifies them; everything else —
  emails, names, ticket bodies — is dropped before it can reach a record.

Timestamps are injected (not read from the clock inside this module) so runs are
reproducible and snapshots are byte-stable.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict

GENESIS_HASH = "0" * 64

# Only these keys survive redaction. Everything else is dropped. This is an
# allowlist, not a denylist: a new field is invisible to the audit log until
# someone deliberately adds it here.
_ALLOWED_DETAIL_KEYS: frozenset[str] = frozenset(
    {
        "action",
        "intent",
        "verdict",
        "code",
        "gate_code",
        "grounding_code",
        "grounded",
        "amount_cents",
        "invoice_id",
        "subscription_id",
        "resolution",
        "confidence",
    }
)


def redact(raw: dict[str, object]) -> dict[str, str]:
    """Keep only allowlisted, non-PII fields; stringify their values."""
    return {k: str(v) for k, v in raw.items() if k in _ALLOWED_DETAIL_KEYS}


class AuditRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    timestamp: str
    ticket_id: str
    customer_id: str
    kind: str
    action_type: str
    verdict: str
    code: str
    grounded: bool
    detail: dict[str, str]
    prev_hash: str
    hash: str

    def payload(self) -> dict[str, object]:
        """The hashed content — every field except ``hash`` itself."""
        return {
            "seq": self.seq,
            "timestamp": self.timestamp,
            "ticket_id": self.ticket_id,
            "customer_id": self.customer_id,
            "kind": self.kind,
            "action_type": self.action_type,
            "verdict": self.verdict,
            "code": self.code,
            "grounded": self.grounded,
            "detail": self.detail,
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self) -> str:
        return _hash_payload(self.payload())


def _hash_payload(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLog:
    """An in-memory, append-only hash chain of audit records."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    @property
    def records(self) -> list[AuditRecord]:
        return list(self._records)

    @property
    def head_hash(self) -> str:
        return self._records[-1].hash if self._records else GENESIS_HASH

    def append(
        self,
        *,
        ticket_id: str,
        customer_id: str,
        kind: str,
        action_type: str,
        verdict: str,
        code: str,
        grounded: bool,
        detail: dict[str, str],
        timestamp: str,
    ) -> AuditRecord:
        seq = len(self._records)
        prev_hash = self.head_hash
        payload = {
            "seq": seq,
            "timestamp": timestamp,
            "ticket_id": ticket_id,
            "customer_id": customer_id,
            "kind": kind,
            "action_type": action_type,
            "verdict": verdict,
            "code": code,
            "grounded": grounded,
            "detail": detail,
            "prev_hash": prev_hash,
        }
        record = AuditRecord(hash=_hash_payload(payload), **payload)  # type: ignore[arg-type]
        self._records.append(record)
        return record

    def to_jsonl(self) -> str:
        return "\n".join(r.model_dump_json() for r in self._records)

    @classmethod
    def from_jsonl(cls, text: str) -> AuditLog:
        log = cls()
        for line in text.splitlines():
            line = line.strip()
            if line:
                log._records.append(AuditRecord.model_validate_json(line))
        return log


def verify_chain(records: list[AuditRecord]) -> bool:
    """Return True iff the records form an intact, sequential hash chain."""
    prev_hash = GENESIS_HASH
    for expected_seq, record in enumerate(records):
        if record.seq != expected_seq:
            return False
        if record.prev_hash != prev_hash:
            return False
        if record.compute_hash() != record.hash:
            return False
        prev_hash = record.hash
    return True
