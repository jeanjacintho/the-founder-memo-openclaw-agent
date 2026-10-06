"""record_memo.py -- the delivered memo onto its night's wiki page."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from conftest import load_module
from wiki import MEMOS, Wiki, split_page

record = load_module("record_memo", "memo-render/scripts/record_memo.py")
NOW = datetime(2026, 10, 2, 5, 12, tzinfo=timezone.utc)


def rec(rank):
    return {"headline": f"Priority {rank}", "body": "Because Acme's pilot ends Friday.",
            "evidence": [{"claim": "The pilot ends Friday", "source": "Acme thread",
                          "url": "https://mail.example/private/t1"}],
            "first_step": f"Step {rank}: send the security review.",
            "advisor": {"name": "Patrick Salyer", "quote": f"Quote {rank}.", "url": f"https://salyer.example/{rank}"}}


CARD = {"recommendations": [rec(1), rec(2), rec(3)], "questions": ["Q1 — Is the budget approved?"]}


@pytest.fixture
def memo_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PLOW_HOME_CHANNEL", "cht_1")

    def write(**memo):
        path = tmp_path / "edition.json"
        path.write_text(json.dumps({"date": "2026-10-02", "language": "English",
                                    "run": {"usd": 80.0, "minutes": 230}, **memo}))
        return path
    return write


def page(mac):
    return (mac.home / "Plow/wiki" / MEMOS / "2026-10-02.md").read_text()


def test_record_memo_writes_the_outcome_page(mac, memo_file):
    out = record.record(Wiki(mac.call_tool), memo_file(priority=CARD), "cht_1", NOW)
    assert out == f"RECORDED {MEMOS}/2026-10-02.md"
    text = page(mac)
    assert text.count("FIRST STEP:") == 3 and "Step 2: send the security review." in text
    meta, _ = split_page(text)
    assert meta["type"] == "Memo" and meta["date"] == "2026-10-02"
    assert meta["priority"]["recommendations"][0]["headline"] == "Priority 1"
    assert mac.wiki("validate", "--writer", "founder-memo")["exit_code"] == 0


def test_private_evidence_urls_are_never_written(mac, memo_file):
    record.record(Wiki(mac.call_tool), memo_file(priority=CARD), "cht_1", NOW)
    text = page(mac)
    assert "mail.example" not in text and "https://salyer.example/1" in text


def test_a_retry_does_not_append_twice_but_still_validates(mac, memo_file):
    w = Wiki(mac.call_tool)
    path = memo_file(priority=CARD)
    record.record(w, path, "cht_1", NOW)
    before = page(mac)
    assert record.record(w, path, "cht_1", NOW).startswith("SKIPPED")
    assert page(mac) == before


def test_a_night_without_a_card_records_its_reason(mac, memo_file):
    record.record(Wiki(mac.call_tool), memo_file(could_not_source=["No round finished."]), "cht_1", NOW)
    text = page(mac)
    assert "Could not source: No round finished." in text and "priority:" not in text
    assert mac.wiki("validate", "--writer", "founder-memo")["exit_code"] == 0


def test_research_text_is_written_inert(mac, memo_file):
    card = json.loads(json.dumps(CARD))
    card["recommendations"][0]["first_step"] = "![x](https://evil.example/p.png) # heading"
    record.record(Wiki(mac.call_tool), memo_file(priority=card), "cht_1", NOW)
    assert "\\!\\[x\\]" in page(mac)


def test_cli_names_a_failure(mac, memo_file, capsys):
    mac.asleep = True
    with pytest.raises(SystemExit, match="error: memo not recorded"):
        record.main([str(memo_file(priority=CARD)), "--now", NOW.isoformat()], call_tool=mac.call_tool)
