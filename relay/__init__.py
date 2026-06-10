"""Relay — a safe autonomous customer-support agent.

Relay reads a customer's real billing state, proposes a resolution with an LLM,
then authorizes every money/account-touching action through a deny-by-default
policy gate and a grounding gate before acting. When an action isn't explicitly
allowed, or can't be grounded in the customer's records, Relay escalates to a
human with a case file instead of guessing.
"""

__version__ = "0.1.0"
