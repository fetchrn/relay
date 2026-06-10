"""Relay's evaluation harness — a small, τ-Bench-style grounded support suite.

A fixed world of customers, subscriptions, and invoices, plus a labeled set of
tickets (ordinary, edge, and adversarial). Run the agent over the suite and the
harness scores resolution, escalation, and — the number that matters —
unsafe-action rate, then writes a schema-validated report.
"""
