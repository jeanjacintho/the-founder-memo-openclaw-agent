#!/usr/bin/env python3
"""run_attempts.py -- stop a paper that keeps failing from re-running all day.

A paper that dies on a provider rate limit (HTTP 429) ends without an edition,
and OpenClaw retries the job: 201 rate-limit errors and 909 model calls in one
afternoon, an owner told nothing. Each retry redoes the whole paper, so the
retries themselves feed the rate limit. This counts the paper's starts on the
owner's day and, past MAX_ATTEMPTS undelivered ones, tells the run to stop
before it spends another model call.

  begin       run once the workspace lock is held, before any research.
              Prints one word:
                proceed      attempt N of MAX_ATTEMPTS; go on
                give-up      the day's attempts are spent and no one has told
                             the owner yet: release the lock, send the owner
                             one message (the edition was not delivered and
                             why it is not trying again), stop
                give-up-quiet  the owner was already told: release the lock, stop
  delivered   run once post_to_chat.py has confirmed the post or staged the
              edition: the day's count starts over

Always exits 0, like run_lock.py, so a cron-fired session reads the word.
The count lives in $PT_HOME/paper-attempts-YYYY-MM-DD.json (the owner's day);
an earlier day's file is removed on the next `begin`.
"""
from __future__ import annotations

import argparse
import json
import sys

from owner_time import owner_now
from pt_paths import pt_home

MAX_ATTEMPTS = 3
PREFIX = "paper-attempts-"


def _path(day):
    return pt_home() / f"{PREFIX}{day.isoformat()}.json"


def _load(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"starts": 0, "told": False}
    if not isinstance(data, dict) or not isinstance(data.get("starts"), int):
        return {"starts": 0, "told": False}
    return {"starts": max(data["starts"], 0), "told": data.get("told") is True}


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _sweep(today):
    for old in pt_home().glob(f"{PREFIX}*.json"):
        if old != _path(today):
            old.unlink(missing_ok=True)


def begin(max_attempts=MAX_ATTEMPTS):
    now = owner_now()
    today = now.date()
    _sweep(today)
    path = _path(today)
    data = _load(path)
    if data["starts"] >= max_attempts:
        word = "give-up-quiet" if data["told"] else "give-up"
        data["told"] = True
        _save(path, data)
        print(word)
        return 0
    data["starts"] += 1
    _save(path, data)
    print("proceed")
    return 0


def delivered():
    _path(owner_now().date()).unlink(missing_ok=True)
    print("cleared")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("begin", help="count this start; proceed or give up")
    start.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    start.set_defaults(func=lambda a: begin(a.max_attempts))
    sub.add_parser("delivered", help="the edition is out: start the count over").set_defaults(func=lambda a: delivered())
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
