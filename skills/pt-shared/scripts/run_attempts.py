#!/usr/bin/env python3
"""run_attempts.py -- stop a paper that keeps failing from re-running all day.

A paper that dies on a provider rate limit (HTTP 429) ends without an edition,
and OpenClaw retries the job: 201 rate-limit errors and 909 model calls in one
afternoon, an owner told nothing. Each retry redoes the whole paper, so the
retries themselves feed the rate limit. This counts the paper's starts on the
owner's day and, past MAX_ATTEMPTS undelivered ones, stops the run before it
spends another model call -- and tells the owner, once, itself.

  begin [--next-paper HH:MM]
              run once the workspace lock is held, before any research.
              Prints one word:
                proceed       attempt N of MAX_ATTEMPTS; go on
                stop          the day's attempts are spent and the owner has been
                              told (now, by this call, or on an earlier start):
                              release the lock and stop
                stop-untold   spent, but the notice could not be posted: release
                              the lock and stop; the owner is still untold, so the
                              next start tries again (and the failure-notice hook
                              still tells them the edition did not arrive)

The notice is sent here, in the same process that records it, in the owner's
own language from the paper's fixed phrases (owner_phrases.py): no model turn
falls between the send and the mark, and no model-written text reaches a
shell. --next-paper is the scheduled paper's delivery hour, for the line that
says when the next try is; without it the line says to ask again later.

The count starts over when post_to_chat.py --clear-attempts confirms a post or
stages the edition (see `clear`). Always exits 0, like run_lock.py, so a
cron-fired session reads the word. The count lives in
$PT_HOME/paper-attempts-YYYY-MM-DD.json (the owner's day).
"""
from __future__ import annotations

import argparse
import json
import sys

from owner_chat import post_owner_text
from owner_phrases import phrase
from owner_time import owner_today
from pt_paths import pt_home

MAX_ATTEMPTS = 3


def _path():
    return pt_home() / f"paper-attempts-{owner_today().isoformat()}.json"


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _notice(next_paper):
    if next_paper:
        return phrase("attempts.spent_scheduled", hour=next_paper)
    return phrase("attempts.spent_on_demand")


def begin(next_paper=None):
    path = _path()
    data = json.loads(path.read_text()) if path.exists() else {"starts": 0, "told": False}
    if data["starts"] < MAX_ATTEMPTS:
        data["starts"] += 1
        word = "proceed"
    else:
        if not data["told"]:
            try:
                post_owner_text(_notice(next_paper))
                data["told"] = True
            except SystemExit as exc:  # the chat post refused or failed: record nothing
                print(f"run_attempts: the spent-day notice was not posted: {exc}", file=sys.stderr)
        word = "stop" if data["told"] else "stop-untold"
    _save(path, data)
    print(word)
    return 0


def clear():
    """The edition is out: the owner's day starts over."""
    _path().unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("begin", help="count this start; proceed, or stop and tell the owner once")
    start.add_argument("--next-paper", metavar="HH:MM", default=None)
    start.set_defaults(func=lambda a: begin(a.next_paper))
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
