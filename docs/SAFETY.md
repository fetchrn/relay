# The fail-closed action contract

Relay's safety rests on a small set of invariants. They are enforced in code and
checked by tests; this document states them so a reviewer can audit the claim.

## INV-1 — The brain cannot execute

The brain returns data (`AgentProposal`), never an effect. The only code that
calls a mutating store method is `Agent._execute`, reached only after both gates
allow. *Tested:* every escalation path in `test_agent.py` asserts the store is
unchanged.

## INV-2 — Deny-by-default authorization

`policy.decide` begins from "not authorized" and returns `ALLOW` only when a
specific allow-rule matches and no deny-rule fires. There is no `else: allow`.
Every unmatched path returns `ESCALATE`. *Tested:* the full escalate/allow matrix
in `test_policy.py`, plus a property test that no over-cap amount auto-executes.

## INV-3 — Authorization is independent of the model

Refund cap, refund window, invoice-paid status, and ownership are checked against
the records in `PolicyContext`, not against anything the brain asserts. A prompt
injection in a ticket body cannot change them because it never reaches them.
*Tested:* `test_injection_*` cases drive a compromised proposal and still escalate.

## INV-4 — Ground before acting

A state-changing action must cite a record that (a) exists in the customer's
scoped records and (b) is the record being changed. Cross-customer and invented
citations are rejected by `grounding.check_grounding`. *Tested:* the cross-
customer and ghost-invoice cases in `test_grounding.py` and `test_agent.py`.

## INV-5 — Per-customer isolation

Retrieval is scoped to the ticket's customer id, so the brain never holds another
customer's records, and the grounding gate independently re-verifies ownership of
every cited id. *Tested:* `test_world_scopes_invoices_per_customer`,
`test_injection_citing_another_customers_invoice_is_blocked`.

## INV-6 — Escalation is always safe

`EscalateAction` is the one action the gates always allow, because handing a
ticket to a human changes no state. Unknown customer, low confidence, sensitive
topic, ungrounded proposal, policy block, and store rejection all converge on
escalation with a `CaseFile`.

## INV-7 — The store cannot be over-driven

Even if both gates were wrong, `store.issue_refund` refuses to refund more than an
invoice's remaining balance and is idempotent by key; `BillingError` fails closed
to escalation. *Tested:* `test_store.py`, `test_store_rejection_fails_closed_to_escalation`.

## INV-8 — Every decision is audited and tamper-evident

Each resolution/escalation appends one record to a hash chain; `verify_chain`
detects any alteration or removal. Records are deny-by-default redacted — PII
never enters them. *Tested:* `test_audit.py`,
`test_each_handled_ticket_appends_one_verifiable_audit_record`.

---

## What is *not* claimed

This is a guarantee about the **action layer**, not about model text. Relay
guarantees the agent cannot *do* an unsafe thing (refund, cancel, leak another
account's records). It does not guarantee the model never *says* something wrong
in a customer reply — answer text is the model's, gated only by confidence and
topic-sensitivity. See [HONESTY.md](HONESTY.md). The honest framing, borrowed
from Sierra's "bounded error rate": treat reliability as a measured property with
a guaranteed floor at the action layer and best-effort filtering above it — not
as "100% safe."
