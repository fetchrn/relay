"""HTTP service surface for Relay.

A thin FastAPI app over the orchestrator. ``POST /tickets`` runs one ticket end
to end and returns the full :class:`~relay.agent.TicketResolution` — outcome,
controlling gate code, customer reply, and (on escalation) the case file. The
default app is wired to the deterministic demo world so it runs with no API key;
pass your own :class:`~relay.agent.Agent` to point it at a real brain and store.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

from relay.agent import Agent, TicketResolution
from relay.brain import MockBrain
from relay.domain import Channel, Ticket
from relay.eval.golden import NOW, build_world


class TicketRequest(BaseModel):
    customer_id: str
    body: str
    subject: str = "support"
    ticket_id: str | None = None


def create_app(agent: Agent | None = None) -> FastAPI:
    app = FastAPI(title="Relay", version="0.1.0", description="Safe autonomous customer support.")
    app.state.agent = agent or Agent(brain=MockBrain(), store=build_world(NOW), clock=lambda: NOW)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "relay"}

    @app.post("/tickets")
    def handle_ticket(req: TicketRequest) -> TicketResolution:
        ticket = Ticket(
            id=req.ticket_id or f"tkt_{uuid.uuid4().hex}",
            customer_id=req.customer_id,
            subject=req.subject,
            body=req.body,
            channel=Channel.API,
            created_at=dt.datetime.now(dt.UTC),
        )
        agent: Agent = app.state.agent
        return agent.handle(ticket)

    return app
