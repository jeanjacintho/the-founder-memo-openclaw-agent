"""The bundled advisors: each file carries the contract the tournament and the renderer read."""
from __future__ import annotations

import re

import pytest
import yaml

from conftest import ROOT, load_module

ADV = ROOT / "memo-setup" / "assets" / "advisors"
SECTIONS = ["## Limits of this advice", "## Questions that change the advice", "## Stage map", "## Sourced words"]
LINE = re.compile(r"^- “(.+)” — \[[^\]]+\]\((https://\S+)\)$", re.M)
FILES = sorted(p for p in ADV.glob("*.md") if p.name != "README.md")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_advisor_file_has_the_contract(path):
    text = path.read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---")[1])
    assert meta["advisor"] and meta["sources"] and all(s.startswith("https://") for s in meta["sources"])
    for section in SECTIONS:
        assert section in text, f"{path.name} lacks {section}"
    sourced = text.split("## Sourced words")[1]
    quotes = LINE.findall(sourced)
    assert len(quotes) >= 12, "too few sourced lines for three distinct winners a night"
    assert len(quotes) == len([l for l in sourced.splitlines() if l.startswith("- ")]), "a sourced line is malformed"
    assert {u for _, u in quotes} <= set(meta["sources"])
    assert len({q for q, _ in quotes}) == len(quotes), "the same line twice"
    assert not any("..." in q or "…" in q for q, _ in quotes), "an elided quote is not verbatim"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_the_renderer_catalog_reads_every_sourced_line(path):
    # render_memo.py replaces render_edition.py in #59's rollout; both carry the same catalog.
    name_ = next(n for n in ("render_memo.py", "render_edition.py") if (ROOT / "memo-render" / "scripts" / n).exists())
    render = load_module("advisor_catalog_renderer", f"memo-render/scripts/{name_}")
    text = path.read_text(encoding="utf-8")
    name = yaml.safe_load(text.split("---")[1])["advisor"]
    quotes = LINE.findall(text.split("## Sourced words")[1])
    catalog = render.advisor_catalog()[name]
    assert {" ".join(q.split()): u for q, u in quotes} == catalog


def test_no_quoted_line_is_shared_across_advisors():
    # The culler's distinct-quote rule spans every advisor's file.
    seen = {}
    for path in FILES:
        for quote, _ in LINE.findall(path.read_text(encoding="utf-8").split("## Sourced words")[1]):
            assert quote not in seen, f"{path.name} repeats {seen.get(quote)}"
            seen[quote] = path.name
