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
                             the owner yet: run `notify` while still holding
                             the lock, then release it and stop
                give-up-quiet  the owner was already told: release the lock, stop

  notify --text TEXT
              post TEXT (one short message in the owner's language: the edition
              was not delivered and the paper is not trying again now) to the
              owner's chat and, in the same process, record that they were told.
              Prints `told`. If the post fails it exits non-zero and records
              nothing, so the next start tries again; one process does both
              steps, so no model turn can fall between the send and the mark.

The count starts over when post_to_chat.py --clear-attempts confirms a post or
stages the edition (see `clear`), not through a command the model has to
remember. Always exits 0, like run_lock.py, so a cron-fired session reads the
word. The count lives in $PT_HOME/paper-attempts-YYYY-MM-DD.json (the owner's
day).
"""
from __future__ import annotations

import argparse
import json
import sys

from owner_time import owner_today
from pt_paths import pt_home

MAX_ATTEMPTS = 3


def _path():
    return pt_home() / f"paper-attempts-{owner_today().isoformat()}.json"


def begin():
    path = _path()
    data = json.loads(path.read_text()) if path.exists() else {"starts": 0, "told": False}
    if data["starts"] >= MAX_ATTEMPTS:
        word = "give-up-quiet" if data["told"] else "give-up"
    else:
        data["starts"] += 1
        word = "proceed"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)
    print(word)
    return 0


def notify(text):
    """Post the spent-day message to the owner's chat, then record that they were told."""
    import post_to_chat  # lazy: post_to_chat imports this module for --clear-attempts
    from bearer_http import post_json
    if not text.strip():
        sys.exit("error: notify needs the message text")
    base, uid, token = post_to_chat.resolve_chat()
    post_json(base, f"/v1/chats/{uid}/messages", token, "Plow Chat", post_to_chat.compose_payload(text.strip()))
    return told()


def told():
    """The owner has been told the day is spent."""
    path = _path()
    data = json.loads(path.read_text()) if path.exists() else {"starts": 0, "told": False}
    data["told"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)
    print("told")
    return 0


def clear():
    """The edition is out: the owner's day starts over."""
    _path().unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("begin", help="count this start; proceed or give up").set_defaults(func=lambda a: begin())
    note = sub.add_parser("notify", help="send the give-up message and record that the owner was told")
    note.add_argument("--text", required=True)
    note.set_defaults(func=lambda a: notify(a.text))
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
