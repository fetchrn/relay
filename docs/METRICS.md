# Metrics: resolution, not deflection

Support-agent vendors converge on one honest headline. Relay uses the same
vocabulary so the numbers mean what an engineer at Decagon, Sierra, Maven AGI,
Ada, or Gradient Labs expects.

## Definitions

| Metric | Definition | In Relay |
|---|---|---|
| **Automated resolution rate** | the customer's problem was actually solved, autonomously, no human, no follow-up | `automated_resolution_rate` = correct **and** resolved / total. **The headline.** |
| **Deflection rate** | the ticket didn't reach a human | `deflection_rate` = resolved / total. Reported, but the *vanity* metric. |
| **Escalation rate** | handed to a human | `escalation_rate` = escalated / total |
| **Accuracy** | outcome matched the labeled expectation | `accuracy` = correct / total |
| **Unsafe-action rate** | a state change executed that should have been blocked | `unsafe_action_rate` = unsafe / total. **Target: 0.** |

## Why deflection is the vanity metric

Deflection counts *any* ticket that didn't reach a human as a win — including
wrong auto-answers and abandonments. So deflection is always **≥** automated
resolution; the gap is the wrong-but-not-escalated tickets. Optimizing deflection
optimizes for hiding tickets from humans, not for solving them. Relay surfaces the
gap (`test_deflection_is_at_least_automated_resolution`) rather than hiding it.

Ada calls the honest version *Automated Resolution Rate (AGR)*; Maven AGI calls it
*autonomous resolution*; Sierra prices on it directly (outcome-based pricing).

## Why unsafe-action rate is the one that matters

Deflection and resolution are business metrics. The unsafe-action rate is a safety
metric, and it's the one a buyer's risk team asks about: did the agent ever issue
a refund outside policy, cancel the wrong subscription, or act on another
customer's account? Relay is architected so this is **zero by construction** (see
[SAFETY.md](SAFETY.md)), and the eval measures it on an adversarial suite to back
the claim with a number rather than an assertion.

## Bounded-error framing

Following Sierra's framing, reliability is presented as a measured property with a
guaranteed floor, not as perfection:

- **Action layer:** guaranteed. The gates make an unsafe *action* impossible by
  construction; the eval confirms 0/16 on the reference suite.
- **Output layer:** best-effort. Answer text is gated on confidence and topic
  sensitivity but is not guaranteed correct. A production deployment adds an
  output classifier and human review on the long tail.

Report both. Never blend them into one "X% safe" number.
