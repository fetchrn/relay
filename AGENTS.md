# AGENTS.md

Guidance for AI coding tools working in this repo.

## What this is
Relay — a safe autonomous customer-support agent. The defining property: **the
LLM proposes, it never executes.** Every money/account-touching action passes a
deny-by-default policy gate and a grounding gate before the store is called.

## Rules
- **Never add `else: allow`** to `relay/policy.py` or `relay/grounding.py`. They are
  pure, deterministic, deny-by-default. Unmatched paths escalate.
- **Authorization stays in code**, never in a prompt. Don't move caps/window/
  ownership checks into the brain.
- **TDD.** Failing test first, then minimal code. Match the surrounding style.
- **Run the gate before finishing:** `ruff format && ruff check && mypy && pytest -q
  && python scripts/leakgate.py .`
- **Regenerate the snapshot** after any behavior change:
  `relay eval --out results/demo`. The snapshot test fails otherwise.
- **No secrets** in code, prompts, fixtures, ticket bodies, or the audit log.
- Use `claude-opus-4-8` with `messages.parse` + structured outputs for the brain;
  adaptive thinking; no `temperature`/`budget_tokens`.

## Map
`domain → store → actions/proposal → brain → grounding + policy → agent → audit`,
with `eval/` (golden suite + harness + report), `service.py`, `cli.py`. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
