#!/usr/bin/env python3
"""Print SETUP_NEEDED or READY for the live-chat first-run gate.

The Plow channel runs this before every owner DM turn and hands the
output to the model; AGENTS.md tells the model to run it itself when that
block is missing.
A missing file, unreadable JSON, or any of the three setup keys absent
(owner.timezone, memo.start, printer.configured)
is SETUP_NEEDED — load memo-setup, do not introduce a general assistant.
READY means the interview already finished; greetings are ordinary turns.

When SETUP_NEEDED, a second line names what `.setup-draft.json` already
holds (or DRAFT:none). Chat history is not progress: a wiped session
still shows old printer turns in the Plow thread.

Exit 0 either way so a missing config is not mistaken for a crashed check.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pt_config_gate as _config_gate
from pt_paths import config_file

_START_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
CONFIG_FILE = str(config_file())


def setup_needed(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=lambda token:
                            (_ for _ in ()).throw(ValueError(f"non-standard JSON constant {token}")))
        return bool(_config_gate.gate(config))
    except (OSError, ValueError, _config_gate.GateError):
        return True
    if not isinstance(config, dict):
        return True
    owner = config.get("owner")
    memo = config.get("memo")
    printer = config.get("printer")
    tz = owner.get("timezone") if isinstance(owner, dict) else None
    hour = memo.get("start") if isinstance(memo, dict) else None
    configured = printer.get("configured") if isinstance(printer, dict) else None
    if not (isinstance(tz, str) and tz.strip()):
        return True
    if not (isinstance(hour, str) and _START_RE.fullmatch(hour)):
        return True
    if not isinstance(configured, bool):
        return True
    return False


def draft_line(config_path):
    """Second gate line: which interview fields the draft already holds."""
    draft_path = Path(config_path).with_name(".setup-draft.json")
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        draft = {}
    if not isinstance(draft, dict):
        draft = {}
    if os.environ.get("MEMO_EVENT"):
        # An event install's hour, printer and Mac come from the event, before any
        # answer: its first turn is the connect question, never the hour.
        import record_setup  # noqa: PLC0415 -- only an event install needs it
        record_setup.apply_event(draft)
    fields = []
    hour = draft.get("start")
    if isinstance(hour, str) and hour.strip():
        fields.append("start")
    printer = draft.get("printer")
    if isinstance(printer, dict) and isinstance(printer.get("configured"), bool):
        fields.append("printer")
    mac = draft.get("mac")
    if isinstance(mac, dict) and isinstance(mac.get("awake"), bool):
        fields.append("awake")
    if draft.get("connected") is True:
        fields.append("connected")
    return "DRAFT:" + (",".join(fields) if fields else "none")


def _language_from(data):
    if not isinstance(data, dict):
        return None
    owner = data.get("owner")
    language = owner.get("language") if isinstance(owner, dict) else None
    if isinstance(language, str) and language.strip():
        return language.strip()
    return None


def owner_language(config_path):
    """The recorded language: draft first (setup), then config (READY).

    Empty string when neither file has a language. language_line() wraps
    this as LANG:…; chat_status.py --busy uses the same value.
    """
    config_path = Path(config_path)
    draft_path = config_path.with_name(".setup-draft.json")
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        draft = None
    from_draft = _language_from(draft)
    if from_draft:
        return from_draft
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = None
    return _language_from(config) or ""


def language_line(config_path):
    """LANG line for every gate reply: draft first (setup), then config (READY).

    This gate is the first action of EVERY live-chat reply, not only while
    setup is unfinished. Measured live 2026-09-18: READY printed no LANG
    line, so after one Portuguese turn the model kept writing Portuguese
    even when the owner switched back to English. The recorded language
    has to ride back on READY too, from pt/config.json, with the in-progress
    draft still winning while SETUP_NEEDED.
    """
    language = owner_language(config_path)
    return "LANG:" + language if language else "LANG:unrecorded"


def main(argv=None):
    argv = sys.argv if argv is None else argv
    path = argv[1] if len(argv) > 1 else CONFIG_FILE
    if setup_needed(path):
        print("SETUP_NEEDED")
        print(draft_line(path))
        print(language_line(path))
    else:
        print("READY")
        print(language_line(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
