#!/usr/bin/env python3
"""Shared structural gate for pt/config.json, the memo's configuration.

This is the SINGLE shared definition of "installed" for the config. It runs
in the agent container, invoked as:

    .../memo-shared/scripts/pt_config_gate.py <config.json>

at setup time (finalize_setup.py runs it before anything lands) and after any
one-line change, so the structural contract lives in one place, single-homed
with references/config.example.json, and no caller can drift from it.

Output contract:
  - Prints the failing invariant name(s) to stdout, joined by "; ".
  - Empty stdout == PASS. Never prints anything else on pass.
  - Prints exactly "not valid JSON" (and nothing else) when the file does not
    parse as JSON, is unreadable, or has a shape the checks themselves could
    not inspect (indexing a non-object, testing a non-string).
  - Never prints PII. There is none by design: the config holds a timezone, a
    start hour, a window, a ceiling, and whether a printer exists.

The checks:
  1. owner.timezone must contain a non-whitespace char: memo.start is the
     owner's clock and the nightly job is registered in that zone.
  2. memo.start must be the exact "HH:MM" shape (00-23 : 00-59): the cron
     spec is built as "<minute> <hour> * * *" from both parts.
  3. memo.window_minutes must be a positive integer: the night's research
     window, and with its publish margin the job's run budget.
  4. memo.max_usd must be a positive number: the night's dollar ceiling.
  5. printer.configured must be a boolean. It is the print path's only gate,
     so a truthy string ("false" reads truthy) would hand memo-print a printer
     that does not exist -- a print leg that fails on every nightly run.
  6. printer.name must be a non-blank string when configured is true: `lp -d`
     needs a destination -- unless printer.url is the https print server of an
     event's shared printer. When configured is false, name may be null or
     absent.
  7. owner.language, when present, is a non-blank string: the language the
     owner writes to this agent in, plain-English name ("Portuguese",
     "Mandarin Chinese"), kept current by memo-intake on every turn so a
     scheduled run -- which has no live message to detect a language from --
     still writes in whatever the owner most recently used.
  8. no string value anywhere may be a leftover [UPPER_SNAKE] placeholder.
  9. priority, when present, has a boolean `configured`.
  10. signals, when present, is an object of group_chat / email / imessage
     booleans. Absent means every source is off.

The owner's name, location, or any other personal fact is deliberately not
among the checks, and not in the schema: location is fetched through Latch at
setup to name the zone, never stored here.
"""
import json
import re
import sys

_PLACEHOLDER_RE = re.compile(r"^\[[A-Z][A-Z0-9_]*\]$")
_NONBLANK_RE = re.compile(r"\S")
# The only shape the start hour may take: any real "HH:MM".
_START_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class GateError(Exception):
    """A structural shape the checks themselves cannot inspect.

    Collapses to "not valid JSON" in main(), exactly as the jq-era gate
    collapsed a filter-level error and a parse failure into that one line.
    """


SIGNAL_SOURCES = ("group_chat", "email", "imessage")


def _index(value, key):
    """dict get with a loud refusal on non-object shapes."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    raise GateError("cannot index non-object")


def _nonblank(value):
    """True when value is a string containing a non-whitespace char."""
    if not isinstance(value, str):
        raise GateError("non-string where a string is required")
    return bool(_NONBLANK_RE.search(value))


def _all_strings(node):
    """Every string reachable by recursive descent."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _all_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_strings(v)


def gate(config):
    """Return the "; "-joined failures for a parsed config (empty == pass).

    Raises GateError for shapes the checks cannot inspect; the caller maps
    that to "not valid JSON".
    """
    failures = []

    # 1. owner.timezone non-blank -- the zone every schedule is written
    #    against and the one thing memo-setup must confirm out loud.
    tz = _index(_index(config, "owner"), "timezone")
    if not _nonblank(tz):
        failures.append("owner.timezone is blank")

    # 2-4. the night: its start hour, its window, its dollar ceiling.
    memo = _index(config, "memo")
    start = _index(memo, "start")
    if not (isinstance(start, str) and _START_RE.fullmatch(start)):
        failures.append('memo.start is not "HH:MM"')
    window = _index(memo, "window_minutes")
    # bool is a subclass of int -- True is 1 -- and is never a number of minutes.
    if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
        failures.append("memo.window_minutes is not a positive integer")
    max_usd = _index(memo, "max_usd")
    if isinstance(max_usd, bool) or not isinstance(max_usd, (int, float)) or max_usd <= 0:
        failures.append("memo.max_usd is not a positive number")

    # 5. printer.configured is a boolean, unambiguously.
    configured = _index(_index(config, "printer"), "configured")
    if not isinstance(configured, bool):
        failures.append("printer.configured is not a boolean")

    # 6. a configured printer has a name (lp -d) or, on an event install, the
    #    https print server of the event's shared printer; an unconfigured one may not.
    if configured is True:
        name = _index(_index(config, "printer"), "name")
        url = _index(_index(config, "printer"), "url")
        url_ok = isinstance(url, str) and url.startswith("https://")
        if not url_ok and not _nonblank(name):
            failures.append("printer.name is blank while printer.configured is true")

    # 7. owner.language, when present, is non-blank. Absent is valid --
    #    memo-render falls back elsewhere, and memo-intake sets this the first
    #    time it has an owner message to detect a language from.
    language = _index(_index(config, "owner"), "language")
    if language is not None and not _nonblank(language):
        failures.append("owner.language is blank")

    # 9. priority, when present, is a boolean switch. Its pages live at fixed paths in the owner's wiki (wiki.py).
    priority = _index(config, "priority")
    if priority is not None and not isinstance(_index(priority, "configured"), bool):
        failures.append("priority.configured is not a boolean")

    # 10. signals, when present, switches the priority-signal sources: an
    #     object whose keys are group_chat / email / imessage, each a boolean.
    #     Absent means every source is off (an install from before signals).
    signals = _index(config, "signals")
    if signals is not None:
        if not isinstance(signals, dict):
            failures.append("signals is not an object")
        else:
            for source, switch in signals.items():
                if source not in SIGNAL_SOURCES:
                    failures.append(f"signals.{source} is not a signal source")
                elif not isinstance(switch, bool):
                    failures.append(f"signals.{source} is not a boolean")

    # 8. no leftover [UPPER_SNAKE] placeholder anywhere.
    if any(_PLACEHOLDER_RE.match(s) for s in _all_strings(config)):
        failures.append("an unfilled [UPPER_SNAKE] placeholder remains")

    return "; ".join(failures)


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: pt_config_gate.py <config.json>\n")
        return 2
    try:
        with open(argv[1], encoding="utf-8") as f:
            # parse_constant fail-closes NaN/Infinity the same way the ld
            # gate does: both parsers accept the non-standard tokens, and a
            # config that parse but cannot be trusted is not valid here.
            config = json.load(
                f, parse_constant=lambda token: (_ for _ in ()).throw(
                    ValueError(f"non-standard JSON constant {token}")))
        failures = gate(config)
    except (OSError, ValueError, GateError):
        print("not valid JSON")
        return 0
    if failures:
        print(failures)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))