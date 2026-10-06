"""render_memo.py -- the memo's fixed page, its escape discipline and its gate."""
from __future__ import annotations

import copy
import json
import sys
import types

import pytest

from conftest import load_module

render = load_module("render_memo", "memo-render/scripts/render_memo.py")

WORDS = {
    "Patrick Salyer": ("Forget the naming (seed / A / B).",
                       "Raise the right amount of money to hit the milestones that unlock the next stage."),
    "Paul Graham": ("Do things that don't scale.", "Make something people want."),
}
URLS = {name: [f"https://example.com/{name.split()[1].lower()}/{i}" for i in range(2)] for name in WORDS}


@pytest.fixture(autouse=True)
def advisors(tmp_path, monkeypatch):
    folder = tmp_path / "advisors"
    folder.mkdir()
    for name, quotes in WORDS.items():
        (folder / f"{name.lower().replace(' ', '-')}.md").write_text(
            f"---\nadvisor: {name}\nsources:\n" + "".join(f"  - {u}\n" for u in URLS[name])
            + "---\n## Framework\nProse is not a quotation.\n## Sourced words\n"
            + "\n".join(f"- “{q}” — [Source]({u})" for q, u in zip(quotes, URLS[name])) + "\n",
            encoding="utf-8")
    monkeypatch.setattr(render, "ADVISORS", folder)
    monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))


def rec(rank, name="Patrick Salyer", i=None):
    i = rank % 2 if i is None else i
    return {"headline": f"Priority {rank}: close the pilot with Acme",
            "body": "Acme's pilot ends Friday and their champion asked for the security review.",
            "evidence": [{"claim": "The pilot ends Friday", "source": "Acme thread", "url": "https://mail.example/t1"}],
            "first_step": "Send Acme the security review today.",
            "advisor": {"name": name, "quote": WORDS[name][i], "url": URLS[name][i]}}


def memo(usd=87.4, **overrides):
    return {"date": "2026-10-02", "language": "English", "run": {"usd": usd, "minutes": 236},
            "priority": {"recommendations": [rec(1, i=0), rec(2, i=1), rec(3, "Paul Graham", 0)],
                         "questions": ["Q1 — Is Acme's budget approved?"]}, **overrides}


def checkpoint(m):
    return {"date": m["date"], "generation": 3, "stage": "generation_3_complete_gate_passed_checkpoint_written",
            "champions": [{"rank": r, "headline": item["headline"]}
                          for r, item in enumerate(m["priority"]["recommendations"], 1)],
            "priority": copy.deepcopy(m["priority"])}


def test_memo_has_three_priorities_questions_and_cost():
    page = render.render(memo())
    assert page.count('class="priority"') == 3 and "Q1 — Is Acme" in page and "$87.40" in page
    assert "3h 56m" in page and "The Founder Memo" in page and "2026-10-02" in page
    assert page.count("FIRST STEP:") == 3


def test_unknown_cost_says_unavailable_not_zero():
    page = render.render(memo(usd=None))
    assert "$0.00" not in page and "cost unavailable" in page


def test_the_cost_line_follows_the_owners_language():
    page = render.render(memo(language="Português"))
    assert "Pesquisa desta noite: US$87.40" in page and "PRIMEIRO PASSO" in page
    assert "2026-10-02" in page and "Oct" not in page


def test_custom_language_without_new_cost_phrases_is_refused(tmp_path):
    import owner_phrases
    old = {k: "ZH " + v for k, v in owner_phrases.SOURCE.items()
           if k not in ("page.cost", "page.cost_unknown")}
    owner_phrases.phrases_file().parent.mkdir(parents=True, exist_ok=True)
    owner_phrases.phrases_file().write_text(json.dumps({"language": "Mandarin Chinese", "phrases": old}))
    with pytest.raises(render.CardError, match="phrases need translation"):
        render.render(memo(language="Mandarin Chinese"))


def test_same_quote_in_two_advisors_files_is_still_refused(advisors, tmp_path):
    # Graham's file carries Salyer's line too: one line, two files, still one quote.
    shared = WORDS["Patrick Salyer"][0]
    path = tmp_path / "advisors" / "paul-graham.md"
    path.write_text(path.read_text().replace(f"“{WORDS['Paul Graham'][0]}”", f"“{shared}”"))
    m = memo()
    m["priority"]["recommendations"][2]["advisor"]["quote"] = shared
    with pytest.raises(render.CardError, match="reuse an advisor quote"):
        render.render(m)


@pytest.mark.parametrize("change, why", [
    (lambda m: m["priority"]["recommendations"].pop(), "exactly 3 items"),
    (lambda m: m["priority"]["recommendations"][0]["advisor"].update(quote="Words nobody said."),
     "not in the named advisor file"),
    (lambda m: m["priority"]["recommendations"][0]["advisor"].update(url=URLS["Patrick Salyer"][1]),
     "does not match its sourced words entry"),
    (lambda m: m["priority"]["recommendations"][0].update(advisor={**m["priority"]["recommendations"][0]["advisor"],
                                                                   "name": "Somebody Else"}),
     "no named advisor file"),
    (lambda m: m["priority"]["recommendations"][1].update(first_step="Open ~/Plow/notes.md first."), "file path"),
    (lambda m: m["priority"]["recommendations"][2].update(body="The founder should call Acme."), "calls the reader"),
    (lambda m: m["run"].update(usd=-1), "run.usd"),
    (lambda m: m.update(could_not_source=["also a reason"]), "exactly one"),
])
def test_a_card_that_cannot_print_is_refused_by_name(change, why):
    m = memo()
    change(m)
    with pytest.raises(render.CardError, match=why):
        render.render(m)


def test_a_night_with_no_checkpoint_prints_its_reason():
    m = {k: v for k, v in memo(usd=None).items() if k != "priority"}
    m["could_not_source"] = ["No round finished before the window closed."]
    page = render.render(m)
    assert "No round finished" in page and 'class="priority"' not in page and "cost unavailable" in page


def test_every_string_is_escaped():
    m = memo()
    m["priority"]["recommendations"][0]["evidence"][0]["claim"] = "<script>alert(1)</script>"
    page = render.render(m)
    assert "<script>" not in page and "&lt;script&gt;" in page


@pytest.mark.parametrize("change, why", [
    (lambda t: t.update(generation=2), "at least 3 completed generations"),
    (lambda t: t.update(stage="generation_3_running"), "completed gated checkpoint"),
    (lambda t: t.update(date="2026-10-01"), "date does not match"),
    (lambda t: [c.update(rank=4 - c["rank"]) for c in t["champions"]], "champions do not match"),
    (lambda t: t["priority"]["questions"].append("Q2 — another"), "priority does not match"),
])
def test_the_card_prints_only_as_its_checkpoint(change, why):
    m = memo()
    t = checkpoint(m)
    assert render.checkpoint_problems(m, t) == []
    change(t)
    assert any(why in p for p in render.checkpoint_problems(m, t))


class FakeHTML:
    pages = [object()]
    def __init__(self, string):
        self.string = string

    def render(self):
        return self

    def write_pdf(self, path):
        with open(path, "w") as f:
            f.write(self.string)


def test_cli_renders_a_card_with_its_checkpoint(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=FakeHTML))
    m = memo()
    (tmp_path / "edition.json").write_text(json.dumps(m))
    (tmp_path / "t.json").write_text(json.dumps(checkpoint(m)))
    pdf = tmp_path / "edition.pdf"
    assert render.main([str(tmp_path / "edition.json"), "--tournament", str(tmp_path / "t.json"), "--pdf", str(pdf)]) == 0
    assert "$87.40" in pdf.read_text() and capsys.readouterr().out.startswith("RENDERED")


def test_cli_refuses_a_card_without_its_checkpoint_and_leaves_no_pdf(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=FakeHTML))
    (tmp_path / "edition.json").write_text(json.dumps(memo()))
    pdf = tmp_path / "edition.pdf"
    pdf.write_text("last night's")
    assert render.main([str(tmp_path / "edition.json"), "--pdf", str(pdf)]) == 1
    assert "only with --tournament" in capsys.readouterr().err
    assert not pdf.exists()


def test_overflow_is_refused_and_removes_the_stale_pdf(tmp_path, monkeypatch, capsys):
    class Overflow(FakeHTML):
        pages = [object(), object()]
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=Overflow))
    m = memo()
    (tmp_path / "edition.json").write_text(json.dumps(m))
    (tmp_path / "t.json").write_text(json.dumps(checkpoint(m)))
    pdf = tmp_path / "memo.pdf"
    pdf.write_text("old memo")
    assert render.main([str(tmp_path / "edition.json"), "--tournament", str(tmp_path / "t.json"), "--pdf", str(pdf)]) == 1
    assert "exceeds one Letter page" in capsys.readouterr().err
    assert not pdf.exists()


def test_the_template_carries_no_script_and_every_slot():
    template = render.TEMPLATE.read_text()
    assert "<script" not in template.lower() and "onload=" not in template.lower()
    for slot in ("LANG", "MASTHEAD", "DATE", "BAND", "BODY", "COST"):
        assert "{{" + slot + "}}" in template
