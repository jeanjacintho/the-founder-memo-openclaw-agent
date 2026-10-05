#!/usr/bin/env python3
"""run_cost.py -- what tonight's run has spent, and whether another generation fits.

    run_cost.py total --since-minutes N [--provider-config PATH]
    run_cost.py can-start --spent <usd|null> --longest <usd> --max <usd>

`total` lists the sessions OpenClaw updated in the last N minutes
(`openclaw sessions --json --limit all --active N`) and prices each one by its
own model: input and output tokens times the USD-per-million price the install
gave that model (boot writes it into the plow provider's config, which this
reads). OpenClaw's listing carries tokens, not dollars. It prints
{"usd": <float or null>, "sessions": n, "unpriced": m}: null when no session
ran on a priced model -- unknown, never $0.00 -- and `unpriced` counts the
sessions whose model has no price, which the total leaves out. A truncated
listing is refused rather than summed short.

Each session's tokens are its latest run's, so a session that ran more than
once (a coordinator resumed after sessions_yield) counts only its last run.

`can-start` exits 0 when one more generation as costly as the costliest so far
still fits under the ceiling, 1 when it does not. An unknown spend cannot hold
the run hostage; the window still bounds it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

OPENCLAW = ["node", "/app/openclaw.mjs"]
PROVIDER_CONFIG = "/etc/plow/openclaw/plow-provider.json5"


def sessions(listing):
    """The listing's rows; a truncated or unexpected listing raises."""
    rows = listing.get("sessions") if isinstance(listing, dict) else None
    if not isinstance(rows, list):
        raise ValueError("not an `openclaw sessions --json` listing")
    if listing.get("hasMore"):
        raise ValueError("the session listing is truncated (hasMore)")
    return rows


def prices(provider):
    """{model id: (input, output) USD per million tokens} for the priced Plow models."""
    return {m["id"]: (float(m["cost"]["input"]), float(m["cost"]["output"]))
            for m in provider.get("models", []) if isinstance(m.get("cost"), dict)}


def cost(row, table):
    """One session's USD, or None when its model has no price or it reported no tokens."""
    price = table.get(row.get("model")) if row.get("modelProvider") == "plow" else None
    tokens = (row.get("inputTokens"), row.get("outputTokens"))
    if price is None or not all(isinstance(t, (int, float)) for t in tokens):
        return None
    return (tokens[0] * price[0] + tokens[1] * price[1]) / 1_000_000


def total(rows, table):
    priced = [c for c in (cost(r, table) for r in rows) if c is not None]
    return round(sum(priced), 4) if priced else None


def unpriced(rows, table):
    """Sessions that used tokens on a model with no price."""
    return sum(1 for r in rows if cost(r, table) is None and (r.get("inputTokens") or r.get("outputTokens")))


def can_start(spent, longest_generation_usd, max_usd):
    return spent is None or spent + longest_generation_usd <= max_usd


def _listing(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout


def main(argv=None, run=_listing):
    p = argparse.ArgumentParser(prog="run_cost.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("total")
    t.add_argument("--since-minutes", type=int, required=True)
    t.add_argument("--provider-config", default=PROVIDER_CONFIG)
    c = sub.add_parser("can-start")
    for flag in ("--spent", "--longest", "--max"):
        c.add_argument(flag, type=lambda v: None if v == "null" else float(v), required=True)
    a = p.parse_args(argv)
    if a.cmd == "can-start":
        return 0 if can_start(a.spent, a.longest, a.max) else 1
    try:
        with open(a.provider_config, encoding="utf-8") as f:
            table = prices(json.load(f))
        rows = sessions(json.loads(run([*OPENCLAW, "sessions", "--json", "--limit", "all",
                                        "--active", str(a.since_minutes)])))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"run_cost: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"usd": total(rows, table), "sessions": len(rows), "unpriced": unpriced(rows, table)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
