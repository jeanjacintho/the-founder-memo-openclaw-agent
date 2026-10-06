#!/usr/bin/env python3
"""history.py -- the cards the memo printed on recent nights, from the wiki.

usage: history.py recent

Prints JSON, oldest first: [{"date", "desk"}], the `priority` card each memo
page of the 7 days before today carries (projects/founder-memo/memos/<date>.md,
written by record_memo.py), or, for a day with no memo, the edition page an
upgraded Founder Times install carried over (projects/founder-memo/editions/). Today's own page is never history: a second run
the same date would otherwise read the first back as "last night".
record_memo.py writes a page only once a memo was delivered, so a card the
owner never received is never history. A day with no page, or no card, is
left out. When the Mac does not answer: `error: history unavailable — <why>`,
non-zero.

"Today" is the owner's own day (`owner_time.owner_today()`), not the
container's -- see that module's docstring for why, and for the same
`error: history unavailable — <why>` refusal on a config that can't be
trusted rather than a guessed window.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "memo-shared" / "scripts"))
from latch_mcp import LatchError
from owner_time import owner_today
from wiki import EDITIONS, MEMOS, connect, split_page

DAYS = 7


def recent(wiki, today):
    out = []
    for back in range(DAYS, 0, -1):
        day = (today - timedelta(days=back)).isoformat()
        # A night's memo, else the edition a Founder Times install carried over (wiki_setup).
        text = wiki.read(f"{MEMOS}/{day}.md") or wiki.read(f"{EDITIONS}/{day}.md")
        card = split_page(text)[0].get("priority") if text else None
        if card:
            out.append({"date": day, "desk": card})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="The cards the memo printed on recent nights.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("recent")
    parser.parse_args(argv)
    try:
        print(json.dumps(recent(connect(), owner_today()), ensure_ascii=False))
    except (LatchError, OSError, ValueError, KeyError, TypeError) as exc:
        sys.exit(f"error: history unavailable — {exc}")


if __name__ == "__main__":
    main()
