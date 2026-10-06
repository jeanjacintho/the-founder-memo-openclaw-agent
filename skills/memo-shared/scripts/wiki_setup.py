#!/usr/bin/env python3
"""wiki_setup.py -- make the owner's wiki ready for The Founder Memo.

usage: wiki_setup.py [--desk]

Idempotent and cheap when there is nothing to do (a few page reads), so every
caller runs it: memo-setup when the advisor's desk is turned on, the desk before
each daily pass (--desk), and record_edition.py before it writes.

  - no ~/Plow/wiki          -> `wiki init ~/Plow/wiki` through Latch's plugin
  - an existing projects/thefoundertimes root -> copy its indexed pages to
    projects/founder-memo once, rewriting links and leaving the old root intact
  - the paper's schema and page, when absent, from memo-shared/assets/wiki/
  - with --desk: entities/owner/goals.md and projects/founder-memo/qa.md, when
    absent. An install from before the wiki carries the body of
    ~/Plow/prioritization.md over once (the old file stays; it is the owner's).
  - projects/founder-memo declared in wiki.toml, when its parsed roots lack it
    (whatever spelling declares them), appended last so a run that failed
    halfway runs again; no other line of the file is touched.

Prints WIKI:ready or `WIKI:set up <what>`. Any failure exits non-zero with
`error: wiki not ready — <why>`.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote

from owner_chat import home_channel
from latch_mcp import LatchError
from wiki import GOALS, OVERVIEW, QA, RESOURCES, ROOT, SCHEMA, WIKI, WRITER, connect, join_page, split_page

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "wiki"
LEGACY_NOTES = "~/Plow/prioritization.md"
LEGACY_ROOT = "projects/thefoundertimes"
LEGACY_OVERVIEW = f"{LEGACY_ROOT}/thefoundertimes.md"


def _seed(wiki, rel, asset, chat, old=lambda: None):
    """Write `rel` from its seed when the wiki lacks it; `old()` is a body to carry over."""
    if wiki.read(rel) is not None:
        return []
    text = (ASSETS / asset).read_text(encoding="utf-8")
    text = text.replace("{today}", datetime.date.today().isoformat()).replace("{chat}", chat)
    body = old()
    if body is not None:
        text = join_page(split_page(text)[0], body)
    wiki.write(rel, text)
    return [rel]


def _copy_legacy(wiki, toml):
    """Declare the new root only after copying; retries keep already-copied pages."""
    roots = tomllib.loads(toml).get("roots", {})
    if ROOT in roots or LEGACY_ROOT not in roots:
        return []
    # A recorded edition can predate a failed index update; enumerate a fresh index.
    code, out = wiki.run("index", write=True)
    if code != 0:
        raise LatchError(f"wiki index: {out.strip()}")
    index = wiki.read("index.md")
    if index is None:
        raise LatchError("wiki index produced no index.md")
    pages = sorted({unquote(rel) for rel in re.findall(rf"\(/({re.escape(LEGACY_ROOT)}/[^)\s]+\.md)\)", index)})
    for rel in pages:
        new = OVERVIEW if rel == LEGACY_OVERVIEW else ROOT + rel[len(LEGACY_ROOT):]
        if wiki.read(new) is None:
            text = wiki.read(rel)
            if text is None:
                raise LatchError(f"legacy wiki page missing: {rel}")
            text = text.replace(LEGACY_OVERVIEW, OVERVIEW).replace(LEGACY_ROOT, ROOT)
            text = text.replace("[The Founder Times](", "[The Founder Memo](")
            if rel == LEGACY_OVERVIEW:
                meta, body = split_page(text)
                canonical, _ = split_page((ASSETS / "overview.md").read_text(encoding="utf-8"))
                meta.update({key: canonical[key] for key in ("title", "description", "tags")})
                body = body.replace("# The Founder Times\n", "# The Founder Memo\n", 1)
                if not re.search(r"^## Memos\s*$", body, re.M):
                    body += "\n## Memos\n"
                text = join_page(meta, body)
            wiki.write(new, text)
    return [f"copied {len(pages)} pages from {LEGACY_ROOT}"] if pages else []


def ensure(wiki, chat, desk=False):
    did = []
    toml = wiki.read("wiki.toml")
    if toml is None:
        code, out = wiki.run("init", WIKI, write=True)
        if code != 0:
            raise LatchError(f"wiki init: {out.strip()}")
        did.append(WIKI)
    else:
        did += _copy_legacy(wiki, toml)
    did += _seed(wiki, SCHEMA, "schema.md", chat)
    did += _seed(wiki, OVERVIEW, "overview.md", chat)
    if desk:
        did += _seed(wiki, GOALS, "goals.md", chat, lambda: wiki.read_path(LEGACY_NOTES))
        did += _seed(wiki, QA, "qa.md", chat)
        did += _seed(wiki, RESOURCES, "resources.md", chat)
    toml = wiki.read("wiki.toml")  # again after the seeds' calls: append to what is there now
    if ROOT not in tomllib.loads(toml).get("roots", {}):
        wiki.write("wiki.toml", f'{toml.rstrip()}\n\n[roots."{ROOT}"]\nwriter = "{WRITER}"\n')
        did.append(f"{ROOT} in wiki.toml")
    return did


def main(argv=None):
    parser = argparse.ArgumentParser(description="Make the owner's wiki ready for the paper.")
    parser.add_argument("--desk", action="store_true",
                        help="also the advisor's desk's pages (goals, the desk's Q&A)")
    args = parser.parse_args(argv)
    try:
        did = ensure(connect(), home_channel(), desk=args.desk)
    except LatchError as exc:
        sys.exit(f"error: wiki not ready — {exc}")
    print("WIKI:" + ("ready" if not did else "set up " + ", ".join(did)))


if __name__ == "__main__":
    main()
