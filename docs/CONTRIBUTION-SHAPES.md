# Contribution shapes

Relay is a reference implementation of a safe autonomous support agent. Here is
how its pieces map onto how specific teams describe their own systems, and the
concrete ways it could extend toward each. (Public framing, 2025–2026.)

## Decagon
Conversational agents that resolve end-to-end, with **human approval on risky
actions** and strict guardrails on refunds + identity. They run a two-phase eval:
offline LLM-as-judge over `{query, context, response}` triplets, then online A/B
with a traffic ramp.
- **Maps to:** Relay's policy gate (human approval = escalation on risky actions),
  the grounding gate (identity/ownership), and the eval harness.
- **Extend:** add an LLM-judge scorer alongside the deterministic one; wire the
  golden suite into a triplet format; add an online-ramp config.

## Sierra
A **"constellation of models"** — a primary agent plus supervisor models ("Jiminy
Crickets") that audit responses and can intercept; the **bounded-error-rate**
framing; creators of **τ-Bench**.
- **Maps to:** the deterministic gate is exactly a deny-by-default supervisor;
  [METRICS.md](METRICS.md) adopts the bounded-error framing; the eval is τ-Bench-
  shaped.
- **Extend:** add an LLM **supervisor** that re-checks the proposal pre-execution
  (defense-in-depth above the deterministic gate); grow the suite toward τ-Bench's
  multi-domain scope.

## Lorikeet
**Defense-in-depth** across agent quality → pre-deploy testing → runtime
guardrails → post-ticket QA, with **response grounding** and **silent escalation**
(queue for review while the agent finishes).
- **Maps to:** the grounding gate (response grounding), the case-file escalation,
  the audit log (post-ticket QA surface).
- **Extend:** add a "silent escalation" mode that flags for review without blocking
  the customer reply; add saved-scenario regression tests.

## Cresta
Real-time guardrails as **concurrent classifier calls** running alongside the main
LLM, able to interrupt; system-prompt rules → input classifiers → adversarial
attacker sims.
- **Maps to:** the two-gate pipeline; the adversarial golden cases are attacker
  sims.
- **Extend:** add an independent input-topic classifier (the sensitive-topic guard
  is currently brain-set); add an adversarial-generation step to grow the suite.

## Gradient Labs
Agent "Otto" for **regulated finance**: domain guardrails + compliance checks,
**detect vulnerable customers**, **route sensitive topics to humans instantly**,
and escalate **with a case file**.
- **Maps to:** the sensitive-topic force-escalation and the `CaseFile` are this,
  directly.
- **Extend:** add a compliance-rule pack to `PolicyConfig`; add vulnerable-customer
  signals to the topic classifier.

## Maven AGI / Ada
Champion **autonomous / automated resolution rate** over deflection as the honest
metric.
- **Maps to:** [METRICS.md](METRICS.md) makes exactly this argument and reports the
  gap.

## Common extension surface
The cleanest first PR into any of these ecosystems is a **scoped issue first**
(several have discuss-before-PR norms), then one of: an LLM-judge scorer, an
independent supervisor model, an adversarial-case generator, or an OTLP exporter
wiring the spans into that team's backend.
