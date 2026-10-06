"""printer.paper "72mm": the roll prints a fixed front page of the memo at 72 mm, not a shrunk Letter page."""
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


def test_the_receipt_is_a_front_page_of_three_slots_questions_one_quote_and_cost():
    page = render.receipt_html(memo())
    assert page.count('class="slot"') == 3
    assert page.index("Priority 1:") < page.index("Priority 2:") < page.index("Priority 3:")
    assert page.count("Send Acme the security review today.") == 3 and page.count("FIRST STEP") == 3
    assert "size: 72mm" in page and "The Founder Memo" in page and "2026-10-02" in page
    assert "What to prioritize today" in page and "QUESTIONS FOR YOU<br>TEXT" in page
    assert "Q1 — Is Acme" in page and "$87.40" in page and "3h 56m" in page
    # The roll is the short version: each body gives only its first sentence (the why), the rest
    # and the evidence stay on the Letter page and in the chat; only the first advisor line prints.
    assert "Acme thread" not in page
    assert "Forget the naming" in page and "Raise the right amount" not in page
    two = memo()
    for item in two["priority"]["recommendations"]:
        item["body"] = "Acme's pilot ends Friday.\n\nTheir champion asked for the security review."
    page = render.receipt_html(two)
    assert page.count('<p class="why">Acme&#x27;s pilot ends Friday.</p>') == 3 and "champion" not in page


def test_the_owners_name_heads_the_roll_escaped_or_is_left_out():
    named = render.receipt_html(memo(), "Ana <Lima>")
    assert '<p class="r-owner">Ana &lt;Lima&gt;</p>' in named
    assert named.index("r-owner\">") < named.index("2026-10-02</p>")
    assert 'class="r-owner"' not in render.receipt_html(memo())


def test_every_slot_is_capped_so_the_roll_stays_short():
    weasyprint = pytest.importorskip("weasyprint")
    worst = memo()
    long = "word " * 200
    for item in worst["priority"]["recommendations"]:
        item.update(headline=long, body=long, first_step=long, advisor={**item["advisor"], "quote": long, "name": long})
    worst["priority"]["questions"] = [long] * 3
    html = weasyprint.HTML(string=render.receipt_html(worst, long)).render().pages[0]._page_box.children[0]
    assert html.margin_height() * 25.4 / 96 < 315  # mm (307 today); uncapped, this memo runs over a meter


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
    assert "The tournament never reached a checkpoint." in page and 'class="slot"' not in page


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


def test_the_slip_and_the_memo_message_carry_the_same_receipt_code(tmp_path, monkeypatch):
    owner_chat = load_module("owner_chat", "memo-shared/scripts/owner_chat.py")
    post = load_module("post_to_chat", "memo-shared/scripts/post_to_chat.py")
    code = owner_chat.receipt_code("cht_attendee")
    assert re.fullmatch(r"#[ABCDEFGHJKMNPQRSTUVWXYZ2-9]{4}", code) and code != owner_chat.receipt_code("cht_other")
    # The slip: write_receipt keys the code on the owner's chat, under the name or alone.
    (tmp_path / "edition.json").write_text(json.dumps(memo()))
    monkeypatch.setattr(owner_chat, "home_channel", lambda: "cht_attendee")
    pages = []
    monkeypatch.setattr(render, "write_pdf", lambda html, path: pages.append(html))
    # The name has its own row at the top; the code (and the phone's last 4, when the rule uses
    # them) is a stub at the bottom, after the advisor line.
    for owner, stub in (((None, None), code), (("Daniel", "4477"), f"{code} · 4477")):
        monkeypatch.setattr(owner_chat, "receipt_owner", lambda owner=owner: owner)
        pe.write_receipt(str(tmp_path / "edition.pdf"))
        page = pages.pop()
        assert f'<p class="r-code"><span>{stub}</span></p>' in page
        assert page.index("<blockquote>") < page.index('class="r-code"') < page.index("<footer>")
        assert ('<p class="r-owner">Daniel</p>' in page) is (owner[0] == "Daniel") and "4477</p>" not in page.split("<blockquote>")[0]
    # The live delivery (post, persisted ticket, print finalizer): at an event, a print the server
    # took posts the "go get it" line with the slip's code; a failed print posts why, as before;
    # a roll at home (no print server) says nothing new.
    config = tmp_path / "config.json"
    event_printer = {"configured": True, "paper": "72mm", "url": "https://print.example/print", "key": "k"}
    monkeypatch.setattr(post, "CONFIG_DEFAULT", str(config))
    monkeypatch.setattr(post, "resolve_chat", lambda: ("https://api.example", "cht_attendee", "tok"))
    monkeypatch.setattr(post, "declare_and_upload", lambda *a, **k: "att_1")
    monkeypatch.setattr(post, "run_record_memo", lambda *a: "RECORDED")
    printed = f"🧾 Your daily report is printed ({code}). Pick it up from the Plow team at the printer."
    home_roll = {"configured": True, "paper": "72mm", "name": "Star_TSP100"}
    for n, (printer, failure, said) in enumerate(((event_printer, None, printed), (home_roll, None, None),
                                                  (event_printer, "page not printed — off", "page not printed — off"))):
        config.write_text(json.dumps({"printer": printer}))
        run = tmp_path / f"run{n}"
        run.mkdir()
        (run / "edition.pdf").write_bytes(b"%PDF")
        (run / "edition.json").write_text(json.dumps(memo()))
        monkeypatch.setenv("PT_HOME", str(tmp_path / f"pt{n}"))
        monkeypatch.setattr(post, "print_page", lambda *a, failure=failure: failure)
        posts = []
        monkeypatch.setattr(post, "post_json", lambda *a: posts.append(a[-1]["body"]))
        monkeypatch.setattr(sys, "argv", ["post_to_chat.py", "--pdf", str(run / "edition.pdf")])
        post.main()
        assert posts == ["", *([said] if said else [])], (printer, failure)


def test_no_owners_chat_yet_prints_the_slip_without_a_code(tmp_path, monkeypatch):
    owner_chat = load_module("owner_chat", "memo-shared/scripts/owner_chat.py")
    (tmp_path / "edition.json").write_text(json.dumps(memo()))
    monkeypatch.setattr(owner_chat, "home_channel", lambda: sys.exit("error: the owner's chat does not exist yet"))
    monkeypatch.setattr(owner_chat, "receipt_owner", lambda: ("Ana Lima", None))
    pages = []
    monkeypatch.setattr(render, "write_pdf", lambda html, path: pages.append(html))
    pe.write_receipt(str(tmp_path / "edition.pdf"))
    assert 'class="r-code"' not in pages[0] and '<p class="r-owner">Ana Lima</p>' in pages[0]
