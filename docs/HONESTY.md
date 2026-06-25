# Honesty statement

What the numbers in this repo claim — and, just as importantly, what they don't.

## What the eval is

A small, fixed, **deterministic** suite: one world of customers/subscriptions/
invoices and 16 labeled tickets, deliberately weighted toward edge and adversarial
cases (prompt injection, cross-customer citation, over-cap / out-of-window
refunds, sensitive topics). It is a **safety stress test**, not a representative
production traffic sample.

## What the headline numbers mean

On the deterministic reference brain (`MockBrain`):

- **`unsafe_action_rate == 0`** — the real claim. Across every adversarial case, no
  unsafe state change executes. This is meaningful because the suite is built to
  *try* to make the agent do unsafe things, and the gates stop all of them. It is
  the expected, correct behavior of a deny-by-default action layer — the value is
  the by-construction guarantee (see [SAFETY.md](SAFETY.md)) plus the measured
  confirmation.
- **`accuracy == 100%`** — expected and not impressive on its own. The reference
  brain is deterministic and the labels encode its correct behavior; 100% here
  means "no gate regressed," which is what the snapshot test guards. It is **not**
  a claim that a real LLM would be 100% correct.
- **`automated_resolution_rate ≈ 23%`** — honest and intentionally conservative.
  The reference brain escalates whenever it is unsure, and the suite is
  adversarial-heavy, so most cases *should* escalate. This is **not** a deflection
  benchmark and should not be read as one. A real, well-tuned LLM brain on
  representative traffic would resolve far more.

## What changes with a real LLM brain

Run `relay eval --brain claude` (needs `ANTHROPIC_API_KEY`) and the picture gets
more interesting and more honest:

- `accuracy` drops below 100% — a real model occasionally proposes the wrong
  action. That's the point of having an eval.
- `deflection_rate` rises above `automated_resolution_rate` — the model sometimes
  resolves a ticket *wrongly* (resolved, not escalated, but incorrect). The gap is
  visible, by design.
- **`unsafe_action_rate` stays 0** — because it is enforced by the gates, not the
  model. This is the load-bearing guarantee, and it does not depend on which brain
  is plugged in.

## Other honest caveats

- The default billing store is in-memory; the Stripe adapter is real but the
  committed eval runs offline against the deterministic store.
- Sensitive-topic detection in `MockBrain` is keyword-based. The `ClaudeBrain`
  classifies, but no classifier is perfect; the safe failure (escalate) is the
  default. A production system should add an independent classifier.
- This guards the **action** layer. It does not guarantee answer *text* is always
  correct — see [SAFETY.md](SAFETY.md) "What is not claimed."
- The dashboard renders the committed snapshot; it is a static report of one run,
  not a live monitor.
