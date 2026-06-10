"""The `relay` command-line interface.

Offline subcommands (`eval`, `run`, `verify-chain`, `schema`) use the
deterministic MockBrain and need no API key. `serve` starts the HTTP service and
`run --brain claude` uses the real model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from relay.agent import Agent
from relay.audit import AuditLog, verify_chain
from relay.brain import Brain, ClaudeBrain, MockBrain
from relay.domain import Channel, Ticket
from relay.eval.golden import NOW, build_world, load_golden
from relay.eval.harness import run_suite
from relay.eval.report import EvalReport


def _brain(name: str) -> Brain:
    return ClaudeBrain() if name == "claude" else MockBrain()


def _cmd_eval(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    audit = AuditLog()
    report = run_suite(
        load_golden(),
        _brain(args.brain),
        build_world,
        brain_name=args.brain,
        generated_at=NOW.isoformat(),
        audit=audit,
    )
    (out / "eval-report.json").write_text(report.to_json() + "\n", encoding="utf-8")
    (out / "eval-report.md").write_text(report.to_markdown(), encoding="utf-8")
    (out / "audit.jsonl").write_text(audit.to_jsonl() + "\n", encoding="utf-8")
    m = report.metrics
    print(
        f"eval: {m.total} cases · automated-resolution {m.automated_resolution_rate:.0%} · "
        f"unsafe-action {m.unsafe_action_rate:.0%} · audit verified={report.audit.verified}"
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    store = build_world(NOW)
    agent = Agent(brain=_brain(args.brain), store=store, clock=lambda: NOW)
    ticket = Ticket(
        id="tkt_cli",
        customer_id=args.customer,
        subject=args.subject,
        body=args.body,
        channel=Channel.API,
        created_at=NOW,
    )
    res = agent.handle(ticket)
    print(res.model_dump_json(indent=2))
    return 0


def _cmd_verify_chain(args: argparse.Namespace) -> int:
    log = AuditLog.from_jsonl(Path(args.file).read_text(encoding="utf-8"))
    ok = verify_chain(log.records)
    print(f"verify-chain: {'OK' if ok else 'FAILED'} ({len(log.records)} records)")
    return 0 if ok else 1


def _cmd_schema(args: argparse.Namespace) -> int:
    Path(args.out).write_text(
        json.dumps(EvalReport.json_schema(), indent=2) + "\n", encoding="utf-8"
    )
    print(f"schema: wrote {args.out}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "serve needs the 'service' extra: pip install 'relay-agent[service]'", file=sys.stderr
        )
        return 1
    from relay.service import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="relay", description="Safe autonomous customer-support agent.")
    sub = p.add_subparsers(dest="command", required=True)

    ev = sub.add_parser("eval", help="run the golden suite and write a report")
    ev.add_argument("--out", default="results/demo")
    ev.add_argument("--brain", choices=["mock", "claude"], default="mock")
    ev.set_defaults(func=_cmd_eval)

    rn = sub.add_parser("run", help="handle one ticket against the demo world")
    rn.add_argument("body")
    rn.add_argument("--customer", default="cus_ada")
    rn.add_argument("--subject", default="support")
    rn.add_argument("--brain", choices=["mock", "claude"], default="mock")
    rn.set_defaults(func=_cmd_run)

    vc = sub.add_parser("verify-chain", help="verify an audit jsonl hash chain")
    vc.add_argument("file")
    vc.set_defaults(func=_cmd_verify_chain)

    sc = sub.add_parser("schema", help="write the eval-report JSON schema")
    sc.add_argument("--out", default="schema/run-report-v1.json")
    sc.set_defaults(func=_cmd_schema)

    sv = sub.add_parser("serve", help="start the HTTP service")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=_cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
