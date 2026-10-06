#!/usr/bin/env python3
"""run_attempts.py -- stop a paper that keeps failing from re-running all day.

A paper that dies on a provider rate limit (HTTP 429) ends without an edition,
and OpenClaw retries the job: 201 rate-limit errors and 909 model calls in one
afternoon, an owner told nothing. Each retry redoes the whole paper, so the
retries themselves feed the rate limit. This counts the paper's starts on the
owner's day and, past MAX_ATTEMPTS undelivered ones, stops the run before it
spends another model call -- and tells the owner, once, itself.

  begin [--key KEY] [--scheduled]
              run once the workspace lock is held (a topic edition holds none),
              before any research. KEY names whose attempts these are: the
              default `paper` is every paper job's shared count; a topic
              edition passes its own topic id, so a failing topic cannot spend
              the main paper's day, nor the other way round.
              Prints one word:
                proceed       attempt N of MAX_ATTEMPTS; go on
                stop          a retry is cooling down or the day's attempts are spent,
                              and the owner has been
                              told (now, by this call, or on an earlier start):
                              release the lock and stop
                stop-untold   blocked, but the notice could not be posted: release
                              the lock and stop; the owner is still untold, so the
                              next start tries again (and the failure-notice hook
                              still tells them the edition did not arrive)

The notice is sent here, in the same process that records it, in the owner's
own language from the paper's fixed phrases (owner_phrases.py): no model turn
falls between the send and the mark, and no model-written text reaches a
shell. --scheduled says the job runs again on its own tomorrow, for the line
that says when the next try is; without it the line says to ask again later.

Retries wait at least two hours after the first start and four after the second.
Cooldown checks do not consume attempts; deadlines are UTC elapsed time, displayed
on the owner's clock. Existing counters without retry_at keep their spent starts.

An explicit owner ask lifts the cap or cooldown once: queue_now (register_crons.py --now)
calls grant(), and the paper's next start proceeds past a spent day, consuming
the grant, so a retry of the same job is capped again.
The count starts over when post_to_chat.py --clear-attempts [KEY] confirms a
post or stages the edition (see `clear`). Always exits 0, like run_lock.py, so a
cron-fired session reads the word. Each count lives in
$PT_HOME/paper-attempts-YYYY-MM-DD[-KEY].json (the owner's day); jobs without
the workspace lock can overlap, so every read-and-write holds a file lock.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from owner_chat import post_owner_text
from owner_phrases import phrase
from owner_time import owner_now, owner_today
from pt_paths import pt_home

MAX_ATTEMPTS = 3
RETRY_SECONDS = (2 * 3600, 4 * 3600)
DEFAULT_KEY = "paper"
KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _path(key=DEFAULT_KEY, day=None):
    if not KEY_RE.fullmatch(key):
        sys.exit(f"error: --key {key!r} has characters not allowed in an attempts key")
    suffix = "" if key == DEFAULT_KEY else f"-{key}"
    return pt_home() / f"paper-attempts-{(day or owner_today()).isoformat()}{suffix}.json"


@contextmanager
def _locked():
    pt_home().mkdir(parents=True, exist_ok=True)
    with open(pt_home() / "paper-attempts.guard", "a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(guard, fcntl.LOCK_UN)


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _notice(scheduled):
    return phrase("attempts.spent_scheduled" if scheduled else "attempts.spent_on_demand")


def _grant_path():
    return pt_home() / "paper-attempts-grant"


def grant():
    """The owner asked for the paper now (queue_now): one start past a spent day.

    A file, not a flag in the job's prompt: OpenClaw re-fires a failed job with
    the same prompt, so a flag would lift the cap on every retry. The first start
    consumes the grant; a retry of that job finds none and meets the cap again.
    """
    with _locked():
        pt_home().mkdir(parents=True, exist_ok=True)
        _grant_path().touch()


def begin(key=DEFAULT_KEY, scheduled=False):
    path = _path(key)
    with _locked():
        now = owner_now()
        data = json.loads(path.read_text()) if path.exists() else {"starts": 0, "told": False}
        # A delay is at most four hours: only yesterday can overlap this owner's day.
        previous = _path(key, owner_today() - timedelta(days=1))
        if not path.exists() and previous.exists():
            prior = json.loads(previous.read_text())
            if prior.get("retry_at") and now.astimezone(timezone.utc) < datetime.fromisoformat(prior["retry_at"]):
                data.update(retry_at=prior["retry_at"], told=prior["told"])
        # Any start of the paper consumes the grant, so none lingers to lift a later retry.
        granted = key == DEFAULT_KEY and _grant_path().exists()
        if granted:
            _grant_path().unlink()
        retry_at = datetime.fromisoformat(data["retry_at"]) if data.get("retry_at") else None
        if not granted and data["starts"] < MAX_ATTEMPTS and retry_at and now.astimezone(timezone.utc) < retry_at:
            if not data["told"]:
                try:
                    post_owner_text(phrase("attempts.cooldown", time=retry_at.astimezone(now.tzinfo).strftime("%Y-%m-%d %H:%M %Z")))
                    data["told"] = True
                except SystemExit as exc:
                    print(f"run_attempts: the cooldown notice was not posted: {exc}", file=sys.stderr)
            word = "stop" if data["told"] else "stop-untold"
        elif data["starts"] < MAX_ATTEMPTS or granted:
            data["starts"] += 1
            data["told"] = False
            if data["starts"] < MAX_ATTEMPTS:
                data["retry_at"] = (now.astimezone(timezone.utc) + timedelta(seconds=RETRY_SECONDS[data["starts"] - 1])).isoformat()
            word = "proceed"
        else:
            if not data["told"]:
                try:
                    post_owner_text(_notice(scheduled))
                    data["told"] = True
                except SystemExit as exc:  # the chat post refused or failed: record nothing
                    print(f"run_attempts: the spent-day notice was not posted: {exc}", file=sys.stderr)
            word = "stop" if data["told"] else "stop-untold"
        _save(path, data)
    print(word)
    return 0


def clear(key=DEFAULT_KEY):
    """The edition is out: the owner's day starts over."""
    with _locked():
        _path(key).unlink(missing_ok=True)
        _path(key, owner_today() - timedelta(days=1)).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("begin", help="count this start; proceed, or stop and tell the owner once")
    start.add_argument("--key", default=DEFAULT_KEY)
    start.add_argument("--scheduled", action="store_true")
    start.set_defaults(func=lambda a: begin(a.key, a.scheduled))
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
