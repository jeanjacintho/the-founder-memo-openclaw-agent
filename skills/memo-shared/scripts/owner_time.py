#!/usr/bin/env python3
"""owner_time.py -- the owner's own clock, from pt/config.json, not the
container's.

Nightly scheduling, run windows, delivery ordering and memo history use
owner.timezone. This is their shared clock; the container's TZ does not
change the owner's day or timestamps.

owner_now()/owner_today() fall back to the container's own clock only when
the config file or the owner.timezone key is genuinely absent. A config
that exists but can't be trusted (bad JSON, an unreadable file, an unknown
zone name) raises instead of guessing -- a silently wrong window or heading
would read as valid.

CLI:

    owner_time.py now                   the owner's now, ISO-8601 with its offset
                                        (memo-tournament records it as the run's start)
    owner_time.py minutes-since ISO     whole minutes since that instant (the run's window)

Bad usage: exit 2.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pt_paths import config_file

# A sentinel, not a Path: PT_HOME (tests point it at a tmp dir, same as
# run_lock.py/record_memo.py) has to be read at call time, not
# baked in as a default at import time.
CONFIG = object()


def _config_path(config_path):
    if config_path is not CONFIG:
        return config_path
    return config_file()


def owner_now(config_path=CONFIG):
    """An aware datetime in the owner's own zone."""
    try:
        config = json.loads(Path(_config_path(config_path)).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return datetime.now().astimezone()
    try:
        tz = config["owner"]["timezone"]
    except (KeyError, TypeError):
        return datetime.now().astimezone()
    return datetime.now(ZoneInfo(tz))


def owner_today(config_path=CONFIG):
    return owner_now(config_path).date()


def minutes_since(iso, config_path=CONFIG):
    """Whole minutes from an aware ISO-8601 instant until the owner's now."""
    then = datetime.fromisoformat(iso)
    if then.tzinfo is None:
        raise ValueError(f"not an instant with an offset: {iso!r}")
    return int((owner_now(config_path) - then).total_seconds() // 60)


USAGE = "usage: owner_time.py now | minutes-since ISO-8601"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv == ["now"]:
            print(owner_now().isoformat(timespec="seconds"))
        elif len(argv) == 2 and argv[0] == "minutes-since":
            print(minutes_since(argv[1]))
        else:
            print(USAGE, file=sys.stderr)
            return 2
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
