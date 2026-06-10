"""Hash-chained, deny-by-default-redacted audit log.

Every decision Relay makes is recorded in an append-only, hash-chained log.
The chain makes tampering detectable: change or drop any record and
``verify_chain`` returns False. Redaction is deny-by-default — only an explicit
allowlist of non-PII fields survives into a record, so customer emails and raw
ticket bodies can never leak into the audit trail.
"""

from __future__ import annotations

from relay.audit import GENESIS_HASH, AuditLog, redact, verify_chain


def _log() -> AuditLog:
    log = AuditLog()
    log.append(
        ticket_id="tkt_1",
        customer_id="cus_1",
        kind="resolved",
        action_type="refund",
        verdict="allow",
        code="refund_ok",
        grounded=True,
        detail={"amount_cents": "2000", "invoice_id": "in_1"},
        timestamp="2025-01-31T00:00:00+00:00",
    )
    log.append(
        ticket_id="tkt_2",
        customer_id="cus_2",
        kind="escalated",
        action_type="refund",
        verdict="escalate",
        code="refund_exceeds_cap",
        grounded=True,
        detail={"amount_cents": "999999"},
        timestamp="2025-01-31T00:01:00+00:00",
    )
    return log


def test_first_record_has_genesis_prev_and_seq_zero() -> None:
    log = _log()
    first = log.records[0]
    assert first.seq == 0
    assert first.prev_hash == GENESIS_HASH


def test_records_chain_by_hash() -> None:
    log = _log()
    assert log.records[1].prev_hash == log.records[0].hash
    assert log.records[1].seq == 1


def test_verify_intact_chain_is_true() -> None:
    log = _log()
    assert verify_chain(log.records) is True


def test_verify_detects_a_tampered_record() -> None:
    log = _log()
    # Flip a recorded amount without recomputing the hash → chain must break.
    tampered = list(log.records)
    tampered[0] = tampered[0].model_copy(
        update={"detail": {"amount_cents": "1", "invoice_id": "in_1"}}
    )
    assert verify_chain(tampered) is False


def test_verify_detects_a_dropped_record() -> None:
    log = _log()
    assert verify_chain([log.records[1]]) is False  # seq jumps / prev mismatch


def test_jsonl_roundtrips_and_still_verifies() -> None:
    log = _log()
    text = log.to_jsonl()
    restored = AuditLog.from_jsonl(text)
    assert [r.hash for r in restored.records] == [r.hash for r in log.records]
    assert verify_chain(restored.records) is True


def test_redact_drops_pii_and_keeps_allowlisted_fields() -> None:
    out = redact(
        {
            "email": "ada@example.com",  # PII — dropped
            "body": "my card number is ...",  # raw ticket text — dropped
            "name": "Ada",  # PII — dropped
            "amount_cents": 2000,  # safe — kept, stringified
            "invoice_id": "in_1",  # safe — kept
            "gate_code": "refund_ok",  # safe — kept
        }
    )
    assert out == {"amount_cents": "2000", "invoice_id": "in_1", "gate_code": "refund_ok"}


def test_redact_stringifies_all_values() -> None:
    out = redact({"grounded": True, "amount_cents": 50})
    assert out == {"grounded": "True", "amount_cents": "50"}
