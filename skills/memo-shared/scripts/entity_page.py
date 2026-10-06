#!/usr/bin/env python3
"""entity_page.py -- merge one investigator's dossier into its shared wiki page.

    entity_page.py merge --dossier <file> [--today YYYY-MM-DD]

The LLM decides what is true; this script decides the page's shape. `## Now` is
replaced, `## Timeline` is merged on (date, item), newest first, capped at 20,
and every other section -- the owner's own -- is kept as written, as is any
timeline line the owner wrote by hand. The page is then validated with the
wiki's own CLI, and a problem fails the run loudly: exit 1, the problem on
stderr. Writes check the expected bytes on the Mac; validation rollback never
restores over an owner save detected since the memo's write.

Dossier: {"kind": "people"|"orgs", "slug": str, "title": str,
          "description": str, "now": str,
          "timeline": [{"date": "YYYY-MM-DD", "fact": str, "item": str}],
          "sources": [{"resource": str}], "tags": [str]}
Facts are paraphrases; `item` is the re-open handle, never an excerpt.

Everything that names the entity -- its kind, slug and title -- travels inside
the dossier file, never on the command line: a name comes from someone else's
mail or invite, and a command line is parsed by a shell before this script can
refuse anything. The investigator writes the file with the write tool and runs
the one fixed command; the slug is refused unless it is one lowercase
kebab-case component, before the Mac is touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date

from latch_mcp import LatchError
from latch_mcp import connect as latch_connect
from wiki import Wiki, join_page, split_page
from owner_time import owner_today
from pt_paths import pt_home
from run_lock import guarded

TYPES = {"people": "Person", "orgs": "Organization"}
CAP = 20
MANAGED = " <!-- memo-managed:"
LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) · (.+) · \{(.+)\}(?: <!-- memo-managed:([a-f0-9]{12}) -->)?$")


def _stamp(line):
    return hashlib.sha256(line.encode()).hexdigest()[:12]


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
    lines = [(line, LINE.match(line)) for line in old.splitlines()]
    # A changed marked bullet is the owner's edit; a stale stamp cannot authorize replacing it.
    managed = lambda line, m: m and m[4] == _stamp(line.split(MANAGED)[0])
    kept = [line for line, m in lines if line.strip() and not managed(line, m)]
    owned = {(m[1], m[3]) for line, m in lines if m and not managed(line, m)}
    entries = {(m[1], m[3]): m[2] for line, m in lines if managed(line, m) and (m[1], m[3]) not in owned}
    entries.update({(e["date"], e["item"]): e["fact"] for e in dossier.get("timeline", [])
                    if (e["date"], e["item"]) not in owned})
    newest = sorted(entries.items(), key=lambda kv: kv[0][0], reverse=True)[:CAP]
    generated = [f"- {d} · {fact} · {{{item}}}" for (d, item), fact in newest]
    timeline = "\n".join(kept + [f"{line}{MANAGED}{_stamp(line)} -->" for line in generated])

    replaced = {"Now": dossier["now"].strip(), "Timeline": timeline}
    out = []
    for head, text in sections:
        if head in replaced:
            text = replaced.pop(head)
        out.append(text if head is None else f"## {head}\n{text.strip()}\n")
    out += [f"## {h}\n{t}\n" for h, t in replaced.items()]  # a new page gets both, in order

    sources = list(meta.get("sources") or [])
    seen = {s["resource"] for s in sources}
    for source in dossier.get("sources", []):
        if source["resource"] not in seen:
            sources.append(source)
            seen.add(source["resource"])
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
    m.add_argument("--dossier", required=True, help="the dossier JSON file, written with the write tool")
    m.add_argument("--today")
    a = p.parse_args(argv)
    rel = a.dossier
    try:
        with open(a.dossier, encoding="utf-8") as f:
            dossier = json.load(f)
        if not isinstance(dossier, dict):
            raise ValueError("the dossier is not a JSON object")
        kind, slug, title = dossier.get("kind"), dossier.get("slug"), dossier.get("title")
        if kind not in TYPES:
            raise ValueError(f"kind must be one of {sorted(TYPES)}")
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise ValueError("slug must be a single lowercase kebab-case component")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("the dossier has no title")
        rel = f"entities/{kind}/{slug}.md"
        w = Wiki(call_tool or latch_connect().call_tool)
        with guarded(pt_home() / "entity-locks" / kind / slug):
            for _ in range(3):
                original = w.read(rel)
                page = merge(original, dossier, kind, title.strip(), a.today or owner_today().isoformat())
                if not w.compare_and_swap(rel, original, page):
                    continue
                try:
                    problems = w._validate("shared", rel)
                    if problems:
                        raise LatchError("wiki validate: " + "; ".join(problems))
                except (OSError, ValueError, KeyError, TypeError, LatchError):
                    w.compare_and_swap(rel, page, original)
                    raise
                break
            else:
                raise LatchError("page changed during merge; retry after the owner finishes editing")
    except (OSError, ValueError, KeyError, TypeError, LatchError) as exc:
        print(f"entity_page: {rel}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
