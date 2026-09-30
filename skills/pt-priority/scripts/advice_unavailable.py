#!/usr/bin/env python3
"""advice_unavailable.py -- the only writer of an "advice unavailable" card, and its proof.

Measured live 2026-09-30: the 07:00 paper had 148 minutes before 09:30, read
the owner's goals, then wrote "the three generations could not be completed"
into run/desk-priority/notes.json without starting one critic. The card said
the tournament failed; it never ran. So the desk no longer writes that file
by hand: this script writes it, and only with a reason it can check.

  window  --deliver-at HH:MM --reason TEXT
      too little time: the paper took today's paper-workspace lock under 50
      minutes before HH:MM. Refused when the window was 50 minutes or more.
  failed  --reason TEXT
      the tournament ran and could not reach an accepted checkpoint. Refused
      unless at least one sub-agent session started after the lock was taken.
  blocked --reason TEXT
      Orient could not reach the owner's wiki. Runs `wiki_setup.py --desk`
      itself; refused when that succeeds.

Every kind needs today's lock (the paper that owns the desk holds it). On
success it writes `{"date", "could_not_source": [reason], "skip": {...}}` and
prints `ADVICE:unavailable <kind>`; a refusal exits non-zero with the reason
and writes nothing. render_edition.py re-checks the same proof with
proof_problem() before it prints the card.
"""
from __future__ import annotations

import argparse
import json
import os
import select
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pt-shared" / "scripts"))
from owner_time import HHMM, owner_now  # noqa: E402
from pt_paths import pt_home  # noqa: E402

# pt-priority/SKILL.md Orient: three generations need about 50 minutes.
MIN_TOURNAMENT_MINUTES = 50
KINDS = ("window", "failed", "blocked")
OPENCLAW = ["node", "/app/openclaw.mjs"]
SESSIONS_ARGV = [*OPENCLAW, "sessions", "list", "--json", "--limit", "all"]
WIKI_SETUP = Path(__file__).resolve().parents[2] / "pt-shared" / "scripts" / "wiki_setup.py"


def today():
    return owner_now().date().isoformat()


def owner_zone():
    return str(owner_now().tzinfo)


def lock_taken_at(run_root, day):
    """When this paper took today's paper-workspace lock, or None."""
    try:
        text = (Path(run_root) / f"paper-workspace-{day}.lock").read_text(encoding="utf-8")
        taken = datetime.fromisoformat(text.strip())
    except (OSError, ValueError):
        return None
    return taken if taken.tzinfo else None


def window_minutes(taken, day, deliver_at, tz):
    """Whole minutes from taking the lock to HH:MM of the owner's `day`."""
    match = HHMM.match(deliver_at or "")
    if not match:
        raise ValueError(f"not an HH:MM time: {deliver_at!r}")
    year, month, date_ = (int(part) for part in day.split("-"))
    target = datetime(year, month, date_, int(match.group(1)), int(match.group(2)),
                      tzinfo=ZoneInfo(tz))
    return int((target - taken).total_seconds() // 60)


def children_since(taken, sessions):
    """Sub-agent sessions that started at or after the lock was taken."""
    since = taken.timestamp() * 1000
    return sum(1 for s in sessions
               if ":subagent:" in str(s.get("key", ""))
               and isinstance(s.get("sessionStartedAt"), (int, float))
               and s["sessionStartedAt"] >= since)


def list_sessions(timeout=60):
    """OpenClaw's stored sessions, or None when they cannot be listed.

    Measured live 2026-09-30: the CLI prints the whole listing at once and
    then never exits, so the listing is read as it arrives and the process is
    stopped as soon as one complete JSON object has been decoded.
    """
    try:
        proc = subprocess.Popen(SESSIONS_ARGV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    buffer, decoder = b"", json.JSONDecoder()
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 1)
            if not ready:
                continue
            chunk = os.read(proc.stdout.fileno(), 65536)
            buffer += chunk
            text = buffer.decode("utf-8", errors="replace")
            start = text.find("{")
            if start >= 0:
                try:
                    listing, _ = decoder.raw_decode(text[start:])
                except ValueError:
                    listing = None
                if isinstance(listing, dict):
                    rows = listing.get("sessions")
                    return rows if isinstance(rows, list) else None
            if not chunk:
                return None
        return None
    finally:
        proc.kill()
        proc.wait()


def wiki_check():
    done = subprocess.run([sys.executable, str(WIKI_SETUP), "--desk"],
                          capture_output=True, text=True, timeout=300)
    lines = (done.stdout + done.stderr).strip().splitlines()
    return done.returncode, (lines[-1] if lines else "")


def proof_problem(notes, run_root, day, tz, sessions_fn):
    """Why an unavailable card is not proven, or None when it is."""
    skip = notes.get("skip") if isinstance(notes, dict) else None
    if not isinstance(skip, dict) or skip.get("kind") not in KINDS:
        return ("desk-priority/notes.json was not written by advice_unavailable.py; "
                "run the tournament, or record why it cannot run with that script")
    taken = lock_taken_at(run_root, day)
    if taken is None:
        return "this paper does not hold today's paper-workspace lock"
    kind = skip["kind"]
    if kind == "window":
        try:
            minutes = window_minutes(taken, day, skip.get("deliver_at"), tz)
        except ValueError as exc:
            return str(exc)
        if minutes >= MIN_TOURNAMENT_MINUTES:
            return (f"the paper took the lock {minutes} minutes before {skip['deliver_at']}, "
                    f"enough for the tournament ({MIN_TOURNAMENT_MINUTES}); run the tournament")
    elif kind == "failed":
        sessions = sessions_fn()
        if sessions is not None and children_since(taken, sessions) == 0:
            return ("no tournament child has started since this paper took the lock; "
                    "a tournament that never ran did not fail -- run it")
    elif not str(skip.get("check") or "").strip():
        return "a blocked desk carries no failed check"
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="kind", required=True)
    window = sub.add_parser("window", help="too little time before the delivery hour")
    window.add_argument("--deliver-at", required=True)
    for name in ("failed", "blocked"):
        sub.add_parser(name)
    for p in sub.choices.values():
        p.add_argument("--reason", required=True, help="the owner-language line the card prints")
    args = parser.parse_args(argv)

    day, run_root = today(), pt_home() / "run"
    taken = lock_taken_at(run_root, day)
    if taken is None:
        sys.exit("error: this paper does not hold today's paper-workspace lock")
    if args.kind == "window":
        skip = {"kind": "window", "deliver_at": args.deliver_at,
                "minutes": window_minutes(taken, day, args.deliver_at, owner_zone())}
    elif args.kind == "failed":
        sessions = list_sessions()
        children = children_since(taken, sessions) if sessions is not None else None
        skip = {"kind": "failed", "children": children}
    else:
        code, last = wiki_check()
        if code == 0:
            sys.exit("error: wiki_setup.py --desk succeeded; the desk is not blocked -- run the tournament")
        skip = {"kind": "blocked", "check": last}
    notes = {"date": day, "could_not_source": [args.reason], "skip": skip}
    problem = proof_problem(notes, run_root, day, owner_zone(), lambda: sessions if args.kind == "failed" else [])
    if problem:
        sys.exit(f"error: {problem}")
    path = run_root / "desk-priority" / "notes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")
    print(f"ADVICE:unavailable {args.kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
