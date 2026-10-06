#!/usr/bin/env python3
"""record_memo.py -- put a delivered memo into the owner's wiki.

usage: record_memo.py <memo.json> [--now <ISO-8601>]

Run once the chat leg is out (post_to_chat.py runs it as a finalizer), never
before: the wiki records what the owner received. The page is
projects/founder-memo/memos/<date>.md (`type: Memo`): each of the night's three
priorities with its `FIRST STEP:` -- what the next night's outcome check looks
for evidence of -- its evidence by claim and source label, and the advisor
line it rests on; then the questions. A night with no card records its
could_not_source reason instead. The page's `priority` frontmatter is the card
itself, which history.py reads back as the desk's history.

Evidence URLs are never written: they are private locators into the owner's
mail and messages, and the wiki is every agent's recall. Every string came
from research and Obsidian renders the page on the owner's Mac, so each is
written through `_md()` (inline syntax and line starts made inert) and each
link through `_url()` (http(s) only).

A memo already recorded (the same memo.json, by hash) is not appended again,
but the wiki is still validated and indexed, so a retry finishes an earlier
check that failed after the write landed. Prints `RECORDED <page>` or
`SKIPPED: <why>`; a failure exits non-zero with `error: memo not recorded —
<why>`, and the delivery it follows still stands.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "memo-shared" / "scripts"))
from latch_mcp import LatchError  # noqa: E402
from owner_chat import home_channel  # noqa: E402
from owner_time import owner_now  # noqa: E402
from wiki import MEMOS, PAPER_LINK, Wiki, connect, join_page, split_page  # noqa: E402
from wiki_setup import ensure  # noqa: E402

MARK = "<!-- memo {} -->"
# Inline characters that open Markdown, HTML or Obsidian syntax (image, link,
# embed, code, emphasis), escaped wherever they appear.
_INLINE = re.compile(r"([\\`*_\[\]!])")
# Obsidian's paired markers: %%comment%%, ==highlight==, ~~strike~~.
_PAIRS = re.compile(r"(%%|==|~~)")
# What a line may start with to become a heading, list, quote or table.
_LINE_START = re.compile(r"^(\s*)([#+\-*>|]|\d+[.)])")


def _md(text, block=False):
    """Research text as inert Markdown. A single-line field folds its newlines."""
    text = str(text if text is not None else "")
    if not block:
        text = " ".join(text.split())
    text = _INLINE.sub(r"\\\1", text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = _PAIRS.sub(lambda m: m.group(0)[0] + "\\" + m.group(0)[1], text)
    return "\n".join(_LINE_START.sub(_inert_start, line) for line in text.split("\n"))


def _inert_start(match):
    indent, marker = match.group(1), match.group(2)
    if marker[0].isdigit():
        return indent + marker[:-1] + "\\" + marker[-1]
    return indent + "\\" + marker


def _url(url):
    """An http(s) link with nothing in it Markdown could read as syntax, else None."""
    url = str(url or "").strip()
    try:
        scheme = urllib.parse.urlsplit(url).scheme.lower()
    except ValueError:
        return None
    if scheme not in ("http", "https"):
        return None
    return urllib.parse.quote(url, safe=":/?#@&=+;,%~-._!$'*")


def archived_card(priority):
    """The card as history keeps it: every evidence URL dropped."""
    return {**priority, "recommendations": [
        {**item, "evidence": [{k: v for k, v in fact.items() if k != "url"} for fact in item["evidence"]]}
        for item in priority["recommendations"]]}


def body_lines(memo):
    if "priority" not in memo:
        return [f"- Could not source: {_md(reason)}" for reason in memo["could_not_source"]] + [""]
    lines = []
    for rank, item in enumerate(memo["priority"]["recommendations"], 1):
        advisor = item["advisor"]
        lines += [f"## {rank}. {_md(item['headline'])}", "", _md(item["body"], block=True), "",
                  f"FIRST STEP: {_md(item['first_step'])}", ""]
        lines += [f"- Evidence: {_md(f['claim'])} ({_md(f['source'])})" for f in item["evidence"]]
        lines += [f'- Advisor: "{_md(advisor["quote"])}" — {_md(advisor["name"])} '
                  f'({_url(advisor["url"]) or "unlinked source"})', ""]
    questions = memo["priority"].get("questions") or []
    if questions:
        lines += ["## Questions", ""] + [f"- {_md(q)}" for q in questions] + [""]
    return lines


def record(wiki, memo_json, chat, now):
    raw = Path(memo_json).read_bytes()
    memo = json.loads(raw)
    rel = f"{MEMOS}/{memo['date']}.md"
    mark = MARK.format(hashlib.sha256(raw).hexdigest()[:12])
    ensure(wiki, chat)
    existing = wiki.read(rel)
    already = existing is not None and mark in existing
    if not already:
        card = archived_card(memo["priority"]) if "priority" in memo else None
        urls = [_url(item["advisor"]["url"]) for item in (card or {}).get("recommendations", [])]
        meta = {
            "type": "Memo", "title": f"The Founder Memo, {memo['date']}",
            "description": card["recommendations"][0]["headline"] if card
            else " ".join(memo["could_not_source"][0].split()),
            "category": "projects", "tags": ["memo"], "paper": PAPER_LINK, "date": memo["date"],
            "sources": [{"resource": u} for u in dict.fromkeys(urls) if u] or [{"resource": f"plow-chat:{chat}"}],
            "created": (split_page(existing)[0].get("created") if existing else None) or now.isoformat(timespec="seconds"),
            "updated": now.isoformat(timespec="seconds"),
            **({"priority": card} if card else {}),
        }
        body = [f"# The Founder Memo, {memo['date']}", mark, ""] + body_lines(memo)
        # A second run the same night replaces the page: the memo is one per date.
        wiki.write(rel, join_page(meta, "\n".join(body)))
    wiki.check()
    return f"SKIPPED: {rel} already has this memo" if already else f"RECORDED {rel}"


def main(argv=None, call_tool=None):
    parser = argparse.ArgumentParser(description="Put a delivered memo into the owner's wiki.")
    parser.add_argument("memo_json")
    parser.add_argument("--now", default=None,
                        help="ISO-8601 moment the memo was posted (post_to_chat.py passes it); "
                             "defaults to owner_now() for a manual run")
    args = parser.parse_args(argv)
    try:
        now = datetime.fromisoformat(args.now) if args.now else owner_now()
    except ValueError as exc:
        sys.exit(f"error: --now {args.now!r} is not ISO8601 ({exc})")
    try:
        wiki = connect() if call_tool is None else Wiki(call_tool)
        print(record(wiki, args.memo_json, home_channel(), now))
    except (LatchError, OSError, ValueError, KeyError, TypeError) as exc:
        sys.exit(f"error: memo not recorded — {exc}")
    return 0


if __name__ == "__main__":
    main(sys.argv[1:])
