"""OpenTelemetry tracing for Relay.

Relay instruments every ticket with OpenTelemetry spans (intake → propose →
ground → gate → execute). That is the integration seam with an eval/observability
backend: point an OTLP exporter at Phoenix, Braintrust, Arize, LangSmith, etc.
and the same spans light up there with no code change.

We install a real SDK ``TracerProvider`` if the process doesn't already have one,
so trace ids are valid even with no exporter configured (the default API provider
hands out all-zero ids). Configuring an exporter is the caller's choice.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

_configured = False


def configure() -> None:
    """Idempotently ensure an SDK TracerProvider is installed."""
    global _configured
    if _configured:
        return
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(TracerProvider())
    _configured = True


def get_tracer() -> trace.Tracer:
    configure()
    return trace.get_tracer("relay")


def current_trace_id() -> str | None:
    """The active span's 128-bit trace id as 32 hex chars, or None if unset."""
    ctx = trace.get_current_span().get_span_context()
    if ctx.trace_id == 0:
        return None
    return format(ctx.trace_id, "032x")
