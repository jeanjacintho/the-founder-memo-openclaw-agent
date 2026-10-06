#!/usr/bin/env python3
"""finalize_setup.py -- the ONLY way memo-setup writes pt/config.json.

Measured live (2026-09-16): the close step said "**Write**
/var/lib/plow/pt/config.json from the draft plus those two fields" and
named no command, and nothing in the tree wrote that file. The run had
everything it needed -- printer probed through the AppleScript fallback,
timezone read from the browser, topics saved -- then ran pt_config_gate.py
against a file nobody had created. The gate collapses OSError into "not
valid JSON", so a MISSING file reported as a corrupt one, and the owner was
told the setup "hit a configuration error". Nothing was wrong with the data.

This script is the fix, the same shape record_setup.py is for the draft:
one named command that owns the file, so the close step never has to
improvise a write. It reads the draft, writes the config, and validates it -- refusing, without leaving a partial file behind, rather
than writing something the gate would reject.

Usage:

    finalize_setup.py <config.json path> --owner-tz <IANA zone>

The zone is step 1's answer (from the browser). The start hour is the
draft's, the owner's own wall clock; the window (240 minutes) and the night's
ceiling ($100) are the defaults. Prints CONFIG:written plus the start line on
success; on failure prints why, on stderr, and writes nothing. Then it queues
the one-off memo-bootstrap job a minute out -- once per install
(register_crons.queue_bootstrap) -- and prints `queued:` or `already queued:`.
An event install (MEMO_EVENT) queues its first memo now instead.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "memo-shared" / "scripts"))
sys.path.insert(0, str(_HERE.parent.parent / "memo-schedule" / "scripts"))
import pt_config_gate as _gate  # noqa: E402 -- the contract this must satisfy
import record_setup as _record  # noqa: E402 -- next_question, the completeness rule
import register_crons as _crons  # noqa: E402 -- the bootstrap job's spec


def build(draft, owner_tz):
    """The config.json body for a completed draft. Pure: no I/O."""
    printer = draft.get("printer") or {}
    # owner.language is what a SCHEDULED run writes in. memo-intake keeps it
    # current from live chat, but the first night can run before memo-intake
    # ever does, so setup plants what it recorded. Absent stays absent -- the
    # gate allows that, and an invented default would be a language nobody chose.
    language = (draft.get("owner") or {}).get("language")
    owner = {"timezone": owner_tz}
    if isinstance(language, str) and language.strip():
        owner["language"] = language.strip()
    return {
        "owner": owner,
        "memo": {"start": draft["start"], "window_minutes": WINDOW_MINUTES, "max_usd": MAX_USD},
        "printer": {
            "configured": bool(printer.get("configured")),
            "name": printer.get("name") if printer.get("configured") else None,
            # An event install prints on the event's shared printer line, at 72 mm.
            **({"line": printer["line"], "paper": printer["paper"]} if printer.get("line") else {}),
        },
        "priority": {"configured": True},
        # Every source starts off; the owner turns one on later (memo-intake).
        "signals": {source: False for source in _record.SIGNAL_SOURCES},
    }


WINDOW_MINUTES = 240
MAX_USD = 100


def main(argv=None, backend=None):
    argv = sys.argv if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config_path")
    parser.add_argument("--owner-tz", help="IANA zone from step 1; an event install uses its event's zone")
    args = parser.parse_args(argv[1:])

    config_path = Path(args.config_path)
    draft_path = config_path.with_name(".setup-draft.json")
    if not draft_path.exists():
        print(
            f"error: no setup draft at {draft_path} -- nothing to finalize",
            file=sys.stderr,
        )
        return 1
    draft = _record.load_draft(draft_path)
    pending = _record.next_question(draft)
    if pending != "close":
        print(
            f"error: setup is not finished (still needs: {pending}); "
            "refusing to write a partial config",
            file=sys.stderr,
        )
        return 1

    if not args.owner_tz and draft.get("event"):
        args.owner_tz = json.loads(_record.EVENTS.read_text(encoding="utf-8"))[draft["event"]]["timezone"]
    if not args.owner_tz:
        print("error: --owner-tz is required", file=sys.stderr)
        return 1
    try:
        ZoneInfo(args.owner_tz)
    except (ZoneInfoNotFoundError, ValueError):
        print(f"error: unknown owner timezone {args.owner_tz!r}", file=sys.stderr)
        return 1
    config = build(draft, args.owner_tz)

    # Validated BEFORE it lands: a config the gate would reject must never
    # become the file the daily run reads.
    failures = _gate.gate(config)
    if failures:
        print(f"error: {failures}", file=sys.stderr)
        return 1

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print("CONFIG:written")
    print(f"memo.start={config['memo']['start']} ({args.owner_tz})")
    # The first full-history read of the company, a minute from now, once. An
    # event install runs its first memo instead: the owner is at the event, by
    # the printer, now (the bootstrap prints nothing, and both would want the
    # workspace in the same minute).
    if backend is None:
        backend = _crons.CronBackend()
    try:
        if draft.get("event"):
            _crons.queue_now(backend, _crons.EVENT_WINDOW_MINUTES, args.owner_tz, prompt=_crons.event_prompt())
        else:
            _crons.queue_bootstrap(backend, args.owner_tz, WINDOW_MINUTES, home=config_path.parent)
    except SystemExit as exc:
        print(f"error: the config is written, but {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
