#!/usr/bin/env python3
"""Prove the in-browser demo (dashboard/relay-demo.js) matches the real Python.

Runs every golden case through BOTH the real Python agent and the JavaScript
port (via node), and asserts the outcome + controlling gate code are identical.
If they ever diverge, the browser demo is lying and this fails. Run in CI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from relay.agent import Agent
from relay.brain import MockBrain
from relay.domain import Channel, Ticket
from relay.eval.golden import NOW, build_world, load_golden

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "dashboard" / "relay-demo.js"

NODE_RUNNER = f"""
const {{ relayDecide }} = require({json.dumps(str(JS))});
const inputs = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = inputs.map(function (x) {{
  const r = relayDecide(x[0], x[1]);
  return {{ outcome: r.outcome, gate_code: r.gate_code, executed: r.executed }};
}});
process.stdout.write(JSON.stringify(out));
"""


def python_result(cid: str, body: str) -> dict:
    agent = Agent(brain=MockBrain(), store=build_world(NOW), clock=lambda: NOW)
    res = agent.handle(
        Ticket(
            id="t", customer_id=cid, subject="x", body=body, channel=Channel.EMAIL, created_at=NOW
        )
    )
    return {"outcome": res.outcome.value, "gate_code": res.gate_code, "executed": res.executed}


def main() -> int:
    cases = load_golden()
    inputs = [[c.customer_id, c.body] for c in cases]

    proc = subprocess.run(
        ["node", "-e", NODE_RUNNER],
        input=json.dumps(inputs),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print("node failed:", proc.stderr, file=sys.stderr)
        return 2
    js_results = json.loads(proc.stdout)

    mismatches = 0
    for case, js in zip(cases, js_results, strict=True):
        py = python_result(case.customer_id, case.body)
        if py != js:
            mismatches += 1
            print(f"MISMATCH {case.case_id}:\n  python={py}\n  js    ={js}")
    print(f"\nchecked {len(cases)} cases · mismatches: {mismatches}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
