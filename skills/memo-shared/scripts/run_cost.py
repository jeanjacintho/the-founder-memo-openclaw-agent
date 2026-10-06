#!/usr/bin/env python3
"""The memo's time-bounded spend from OpenClaw transcript usage events.

    run_cost.py total --since-minutes N
    run_cost.py can-start --spent <usd|null> --longest <usd> --max <usd>

Reads the local stores read-only, including every call in a resumed session.
The pinned Agent Index client already shipped in the image owns compressed-event
decoding and timestamp interpretation; this adapter prices its events for the
memo's minute window, without running the reporter or contacting the Index.
Unknown prices or token counts never become a smaller numeric total. Cached
usage requires an explicit cache price too. Unknown spend refuses another
generation; the caller proceeds to Freshness and Publish.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import importlib.util
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time

PROVIDER_CONFIG = "/etc/plow/openclaw/plow-provider.json5"
TOKEN_FIELDS = ("input", "output", "cacheRead", "cacheWrite")


def _client():
    spec = importlib.util.spec_from_file_location("memo_usage_decoder", "/opt/plow/agent-index-client.py")
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    return client


def events(since, until):
    """Every usage call in the window, deduplicated across checkpoint copies."""
    root = Path(os.environ["OPENCLAW_STATE_DIR"])
    stores = sorted(root.glob("agents/*/agent/openclaw-agent.sqlite"))
    if not stores:
        raise ValueError(f"no OpenClaw transcript store under {root}")
    client, rows, seen = _client(), [], set()
    for store in stores:
        with closing(sqlite3.connect(store.as_uri() + "?mode=ro", uri=True)) as db:
            columns = {r[1] for r in db.execute("PRAGMA table_info(transcript_events)")}
            payload = "event_json, event_zstd, event_utf8_bytes" if {"event_zstd", "event_utf8_bytes"} <= columns else "event_json, NULL, NULL"
            for session, raw, blob, size, created in db.execute(f"SELECT session_id, {payload}, created_at FROM transcript_events"):
                event = json.loads(client._event_json(raw, blob, size))
                stamp = client._stamp_ms(event.get("timestamp"), created)
                if not since <= stamp <= until:
                    continue
                message = event.get("message") or {}
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    continue
                response = message.get("responseId")
                if response is not None:
                    if response in seen:
                        continue
                    seen.add(response)
                rows.append({"session": (str(store), session), "model": message.get("model"),
                             "provider": message.get("provider"), "usage": usage})
    return rows


def prices(provider):
    return {m["id"]: m["cost"] for m in provider.get("models", []) if isinstance(m.get("cost"), dict)}


def cost(row, table):
    price = table.get(row.get("model")) if row.get("provider") == "plow" else None
    if price is None:
        return None
    amount = 0
    for field in TOKEN_FIELDS:
        tokens = row["usage"].get(field, 0 if field.startswith("cache") else None)
        rate = price.get(field)
        if not isinstance(tokens, (int, float)) or not math.isfinite(tokens) or tokens < 0:
            return None
        if tokens:
            if not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0:
                return None
            amount += tokens * rate / 1_000_000
    return amount


def summary(rows, table):
    amounts = [cost(row, table) for row in rows]
    unknown = {row["session"] for row, amount in zip(rows, amounts) if amount is None}
    return {"usd": sum(amounts) if amounts and not unknown else None,
            "sessions": len({r["session"] for r in rows}), "unpriced": len(unknown)}


def can_start(spent, longest_generation_usd, max_usd):
    return spent is not None and spent + longest_generation_usd <= max_usd


def main(argv=None):
    p = argparse.ArgumentParser(prog="run_cost.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("total")
    t.add_argument("--since-minutes", type=int, required=True)
    c = sub.add_parser("can-start")
    for flag in ("--spent", "--longest", "--max"):
        c.add_argument(flag, type=lambda v: None if v == "null" else float(v), required=True)
    a = p.parse_args(argv)
    if a.cmd == "can-start":
        return 0 if can_start(a.spent, a.longest, a.max) else 1
    try:
        if a.since_minutes <= 0:
            raise ValueError("--since-minutes must be positive")
        with open(PROVIDER_CONFIG, encoding="utf-8") as f:
            table = prices(json.load(f))
        until = int(time.time() * 1000)
        out = summary(events(until - a.since_minutes * 60_000, until), table)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error) as exc:
        print(f"run_cost: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
