"""printer.paper "72mm": the roll prints the memo's three priorities at 72 mm, not a shrunk Letter page."""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

import pytest

from conftest import ROOT, load_module
from test_render_memo import memo, render

sys.path.insert(0, str(ROOT / "memo-shared" / "scripts"))
pe = load_module("print_edition", "memo-print/scripts/print_edition.py")


def test_the_receipt_has_all_three_priorities_questions_and_cost_at_72mm():
    page = render.receipt_html(memo())
    assert page.count('class="priority"') == 3
    assert page.index("Priority 1:") < page.index("Priority 2:") < page.index("Priority 3:")
    assert "size: 72mm" in page and "The Founder Memo" in page and "2026-10-02" in page
    assert "Q1 — Is Acme" in page and "$87.40" in page and "3h 56m" in page
    assert "QUESTIONS FOR YOU<br>TEXT" in page


def test_the_receipt_embeds_its_fonts_and_renders_one_72mm_page():
    page = render.receipt_html(memo())
    fonts = re.findall(r'url\("(file:[^"]+)"\)', page)
    assert len(fonts) == 4
    assert all(pathlib.Path(urllib.request.url2pathname(urllib.parse.urlparse(u).path)).is_file() for u in fonts)
    weasyprint = pytest.importorskip("weasyprint")  # in the image; `test:py` runs without it
    document = weasyprint.HTML(string=page).render()
    assert len(document.pages) == 1 and round(document.pages[0].width * 25.4 / 96) == 72
    # Every glyph comes from the shipped fonts: no fallback to whatever the machine has.
    embedded = re.findall(rb"/BaseFont\s*/[A-Z]{6}\+([\w-]+)", document.write_pdf(uncompressed_pdf=True))
    assert {name.rsplit(b"-", 1)[0] for name in embedded} == {
        b"Memo-Display-Heavy", b"Memo-Text", b"Memo-Text-Bold", b"Memo-Text-Italic"}


def test_a_night_with_no_checkpoint_prints_its_reason_on_the_roll():
    page = render.receipt_html({"date": "2026-10-02", "language": "English", "run": {"usd": None, "minutes": 5},
                                "could_not_source": ["The tournament never reached a checkpoint."]})
    assert "The tournament never reached a checkpoint." in page and 'class="priority"' not in page


def test_only_a_72mm_roll_gets_the_receipt_and_its_media(tmp_path, monkeypatch):
    (tmp_path / "edition.json").write_text(json.dumps({"date": "2026-10-02"}))
    (tmp_path / "edition.pdf").write_bytes(b"%PDF-1.4 fake")
    shipped = []
    monkeypatch.setattr(pe, "connect", lambda: type("S", (), {"call_tool": None})())
    monkeypatch.setattr(pe, "ship", lambda pdf, printer, date, call, opts=(): shipped.append((pdf, list(opts))))
    monkeypatch.setattr(pe, "write_receipt", lambda pdf: "/run/receipt.pdf")
    for paper, expected in ((None, (str(tmp_path / "edition.pdf"), [])),
                            ("72mm", ("/run/receipt.pdf", ["-o", "media=X72MMY2000MM"]))):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"printer": {"configured": True, "name": "Star_TSP100",
                                                  **({"paper": paper} if paper else {})}}))
        pe.main([str(tmp_path / "edition.pdf"), str(config)])
        assert shipped.pop() == expected
