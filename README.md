# Relay

**A safe autonomous customer-support agent.** Relay reads a customer's real billing
state, decides how to resolve their ticket with an LLM, and then — before it does
anything that touches money or account state — runs the proposed action through a
**deny-by-default policy gate** and a **grounding gate**. If the action isn't
explicitly authorized by policy, or the agent can't ground it in the customer's
actual records, Relay **escalates to a human instead of guessing.**

The headline number for a support agent is its **deflection rate** — the fraction of
tickets it resolves end-to-end with no human. The number that gets you fired is the
**unsafe-action rate** — refunds issued outside policy, the wrong customer's data
leaked, a subscription cancelled it had no business cancelling. Relay is built so the
second number is **zero by construction**, and proves it on an adversarial eval set.

> Full README, architecture, honesty statement, threat model, and live demo links are
> filled in as the build completes. This file is the project's front door.
