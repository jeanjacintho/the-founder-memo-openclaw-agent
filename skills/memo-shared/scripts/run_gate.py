#!/usr/bin/env python3
"""run_gate.py -- wait for the owner's Mac, never past the night's window.

    run_gate.py wait --started <ISO-8601> --window <minutes>

The night researches only through the Mac (Latch). This probes it with one
plow_read_file of ~/Plow/wiki/wiki.toml -- an answer of any kind, "no such
file" included, is the Mac awake -- and, while it does not answer, probes
again every five minutes until the window that opened at --started closes.

One call waits at most MAX_WAIT_SECONDS, under OpenClaw's 30-minute exec
timeout; the conductor calls again on exit 3. Prints one line and exits:

    MAC:reachable      0   start the night
    MAC:window-closed  2   the window closed with the Mac never answering
    MAC:still-waiting  3   call again with the same --started
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from latch_mcp import LatchError
from latch_mcp import connect as latch_connect

PROBE = "~/Plow/wiki/wiki.toml"
INTERVAL_SECONDS = 300
MAX_WAIT_SECONDS = 1500
LINES = {0: "MAC:reachable", 2: "MAC:window-closed", 3: "MAC:still-waiting"}


def _now():
    return datetime.now().astimezone()


def reachable(call_tool):
    try:
        call_tool("plow_read_file", {"path": PROBE})
    except LatchError as exc:
        return "ENOENT" in str(exc)
    return True


def wait(call_tool, started, window_minutes, sleep=time.sleep, now=_now, max_wait_seconds=None):
    """0 when the Mac answers, 2 when the window closed first, 3 when this call's own wait ran out."""
    called = now()
    while True:
        remaining = window_minutes * 60 - (now() - started).total_seconds()
        if remaining <= 0:
            return 2
        answered = reachable(call_tool)
        remaining = window_minutes * 60 - (now() - started).total_seconds()
        if remaining <= 0:
            return 2
        if answered:
            return 0
        if max_wait_seconds is not None and (now() - called).total_seconds() + INTERVAL_SECONDS > max_wait_seconds:
            return 3
        sleep(min(INTERVAL_SECONDS, remaining))


def main(argv=None, call_tool=None):
    p = argparse.ArgumentParser(prog="run_gate.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait")
    w.add_argument("--started", type=datetime.fromisoformat, required=True)
    w.add_argument("--window", type=int, required=True)
    a = p.parse_args(argv)
    started = a.started if a.started.tzinfo else a.started.astimezone()
    code = wait(call_tool or latch_connect().call_tool, started, a.window,
                sleep=time.sleep, now=_now, max_wait_seconds=MAX_WAIT_SECONDS)
    print(LINES[code])
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
