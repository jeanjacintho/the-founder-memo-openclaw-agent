#!/usr/bin/env python3
"""entity_page.py -- merge one investigator's dossier into its shared wiki page.

    entity_page.py merge --kind people|orgs --slug <slug> --title <title> --dossier <file|-> [--today YYYY-MM-DD]

The LLM decides what is true; this script decides the page's shape. `## Now` is
replaced, `## Timeline` is merged on (date, item), newest first, capped at 20,
and every other section -- the owner's own -- is kept as written, as is any
timeline line the owner wrote by hand. The page is then validated with the
wiki's own CLI, and a problem fails the run loudly: exit 1, the problem on
stderr, never a half-merged page left standing as if it were fine.

Dossier: {"description": str, "now": str,
          "timeline": [{"date": "YYYY-MM-DD", "fact": str, "item": str}],
          "sources": [{"resource": str}], "tags": [str]}
Facts are paraphrases; `item` is the re-open handle, never an excerpt.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

from latch_mcp import LatchError
from latch_mcp import connect as latch_connect
from wiki import Wiki, join_page, split_page

TYPES = {"people": "Person", "orgs": "Organization"}
CAP = 20
LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) · (.+) · \{(.+)\}$")


def _check(dossier):
    if not isinstance(dossier.get("now"), str) or not dossier["now"].strip():
        raise ValueError("dossier has no `now`")
    for e in dossier.get("timeline", []):
        date.fromisoformat(e["date"])  # ValueError on "Friday"
        if not e.get("item") or not e.get("fact"):
            raise ValueError(f"timeline entry without fact or item: {e}")


def _sections(body):
    """[(heading or None, text)] split on level-2 headings, order kept."""
    out, head, buf = [], None, []
    for line in body.splitlines():
        if line.startswith("## "):
            out.append((head, "\n".join(buf)))
            head, buf = line[3:].strip(), []
        else:
            buf.append(line)
    out.append((head, "\n".join(buf)))
    return out


def merge(existing, dossier, kind, title, today):
    _check(dossier)
    meta, body = split_page(existing) if existing else ({}, f"# {title}\n")
    sections = _sections(body)
    old = dict(sections).get("Timeline", "")
    kept = [line for line in old.splitlines() if line.strip() and not LINE.match(line)]
    entries = {(m[1], m[3]): m[2] for m in (LINE.match(line) for line in old.splitlines()) if m}
    entries.update({(e["date"], e["item"]): e["fact"] for e in dossier.get("timeline", [])})
    newest = sorted(entries.items(), key=lambda kv: kv[0][0], reverse=True)[:CAP]
    timeline = "\n".join(kept + [f"- {d} · {fact} · {{{item}}}" for (d, item), fact in newest])

    replaced = {"Now": dossier["now"].strip(), "Timeline": timeline}
    out = []
    for head, text in sections:
        if head in replaced:
            text = replaced.pop(head)
        out.append(text if head is None else f"## {head}\n{text.strip()}\n")
    out += [f"## {h}\n{t}\n" for h, t in replaced.items()]  # a new page gets both, in order

    sources = list(meta.get("sources") or [])
    seen = {s["resource"] for s in sources}
    sources += [s for s in dossier.get("sources", []) if s["resource"] not in seen]
    meta.update({
        "type": TYPES[kind], "title": meta.get("title", title),
        "description": dossier.get("description") or meta.get("description", title),
        "category": "entities",
        "tags": sorted(set(meta.get("tags", [])) | set(dossier.get("tags", [])) | {kind}),
        "sources": sources, "created": meta.get("created", today), "updated": today,
    })
    return join_page(meta, "\n".join(s.rstrip() + "\n" for s in out if s.strip()))


def main(argv=None, call_tool=None):
    p = argparse.ArgumentParser(prog="entity_page.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--kind", choices=sorted(TYPES), required=True)
    m.add_argument("--slug", required=True)
    m.add_argument("--title", required=True)
    m.add_argument("--dossier", required=True)
    m.add_argument("--today", default=date.today().isoformat())
    a = p.parse_args(argv)
    rel = f"entities/{a.kind}/{a.slug}.md"
    try:
        with (sys.stdin if a.dossier == "-" else open(a.dossier, encoding="utf-8")) as f:
            dossier = json.load(f)
        w = Wiki(call_tool or latch_connect().call_tool)
        page = merge(w.read(rel), dossier, a.kind, a.title, a.today)
        w.write(rel, page)
        code, out = w.run("validate", "--writer", "shared")
    except (OSError, ValueError, KeyError, TypeError, LatchError) as exc:
        print(f"entity_page: {rel}: {exc}", file=sys.stderr)
        return 1
    mine = [line for line in out.splitlines() if line.startswith(rel)]
    if mine or code not in (0, 1):
        print("entity_page: wiki validate: " + ("; ".join(mine) or out.strip()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
