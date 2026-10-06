#!/usr/bin/env python3
"""The owner's DM uid: PLOW_HOME_CHANNEL, or asked of Plow when that is blank.

    /opt/plow/skills/memo-shared/scripts/owner_chat.py     # prints the uid

Boot exports PLOW_HOME_CHANNEL when `/v1/agents/me` already lists the owner's
chat. A line whose owner has not texted yet has no such chat at boot, so the
variable stays blank until the next restart; this asks the same identity
endpoint again and applies the rule the Plow channel plugin uses
(`findOwnerChat`): the one active chat with exactly two participants, this
agent on its own line and a member whose role is owner. Nothing is cached or
written -- a uid pasted into config would outlive the chat it names.

Failure exits loudly by name, like bearer_http.require: a blank or ambiguous
answer must never read like "post nowhere".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bearer_http import TIMEOUT, open_no_redirect, post_json, require  # noqa: E402


def find_owner_chat(identity: dict) -> str | None:
    """The owner's DM uid in an identity document, None when there is none yet."""
    line = (identity.get("line") or {}).get("uid")
    owners = [
        chat for chat in identity.get("chats") or []
        if chat.get("status") == "active"
        and len(chat.get("participants") or []) == 2
        and any(p.get("type") == "agent" and p.get("relationship") == "self"
                and (p.get("line") or {}).get("uid") == line for p in chat["participants"])
        and any(p.get("type") == "member" and p.get("role") == "owner" for p in chat["participants"])
    ]
    if len(owners) > 1:
        raise ValueError(f"expected one owner's chat; found {len(owners)}")
    return owners[0]["uid"] if owners else None


def fetch_identity(base: str, token: str) -> dict:
    request = urllib.request.Request(
        url=f"{base.rstrip('/')}/v1/agents/me",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with open_no_redirect(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"error: /v1/agents/me returned HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        sys.exit(f"error: GET /v1/agents/me failed: {exc.reason}")
    except ValueError as exc:
        sys.exit(f"error: /v1/agents/me returned a non-JSON response: {exc!r}")


def home_channel() -> str:
    """PLOW_HOME_CHANNEL when set, else the owner's chat from `/v1/agents/me`."""
    value = os.environ.get("PLOW_HOME_CHANNEL", "").strip()
    if value:
        return value
    identity = fetch_identity(require("PLOW_API_BASE"), require("PLOW_AGENT_TOKEN"))
    try:
        uid = find_owner_chat(identity)
    except ValueError as exc:
        sys.exit(f"error: PLOW_HOME_CHANNEL is not set and {exc}")
    if not uid:
        sys.exit("error: PLOW_HOME_CHANNEL is not set and the owner's chat does not exist yet")
    return uid


# No 0/O, 1/I/L: a code read off paper at an event is never mistyped.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def receipt_code(chat_uid: str) -> str:
    """The owner's receipt code, "#" and 4 characters, from their DM's uid: the slip and
    the memo message print the same one, so a slip and a phone match on the spot.
    ponytail: 31^4 = 923,521 codes; 100 attendees repeat one about 0.5% of the time."""
    digest = hashlib.sha256(chat_uid.encode("utf-8")).digest()
    return "#" + "".join(CODE_ALPHABET[b % len(CODE_ALPHABET)] for b in digest[:4])


def receipt_owner() -> tuple[str | None, str | None]:
    """(name, last 4 phone digits) for the receipt, the CEO's rule (2026-10-06); either may be None.

    The name row: a first and last name as is, else the one name Plow has, else an
    address's part before the @. The digits go beside the receipt code at the
    bottom whenever there is no full name and the owner has a phone. Never the
    whole number or address. Never exits: a receipt without them still prints."""
    try:
        identity = fetch_identity(require("PLOW_API_BASE"), require("PLOW_AGENT_TOKEN"))
    except (SystemExit, Exception):  # noqa: BLE001 -- the name is decoration, the print is not
        return None, None
    owners = [p for chat in identity.get("chats") or [] if chat.get("status") == "active"
              for p in chat.get("participants") or [] if p.get("type") == "member" and p.get("role") == "owner"]
    for owner in owners:
        name = " ".join(str(owner.get("display_name") or "").split())
        handle = str(owner.get("provider_key") or "").strip()
        if "@" in name or not re.search(r"[^\W\d_]", name):  # Plow fell back to the handle itself
            handle, name = handle or name, ""
        if "@" in handle:
            name, digits = name or handle.split("@", 1)[0], ""
        else:
            digits = re.sub(r"\D", "", handle)[-4:]
        digits = digits if len(digits) == 4 and len(name.split()) < 2 else ""
        if name or digits:
            return name or None, digits or None
    return None, None


def post_owner_text(text: str) -> None:
    """Post one plain text message to the owner's chat (setup's hang-on, the spent-day notice)."""
    base = require("PLOW_API_BASE").rstrip("/")
    post_json(base, f"/v1/chats/{home_channel()}/messages", require("PLOW_AGENT_TOKEN"), "Plow Chat", {"body": text})


if __name__ == "__main__":
    print(home_channel())
