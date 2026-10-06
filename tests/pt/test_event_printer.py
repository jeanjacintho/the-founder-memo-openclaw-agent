"""An event install (MEMO_EVENT): no printer or Mac questions, its first memo runs
now, and the receipt goes to the event's shared printer line over Plow."""
from __future__ import annotations

import json
import sys

import pytest

from conftest import ROOT, load_module
from test_finalize_setup import FakeScheduler

sys.path.insert(0, str(ROOT / "memo-shared" / "scripts"))
record = load_module("record_setup", "memo-shared/scripts/record_setup.py")
finalize = load_module("finalize_setup", "memo-setup/scripts/finalize_setup.py")
gate = load_module("pt_config_gate", "memo-shared/scripts/pt_config_gate.py")
pe = load_module("print_edition", "memo-print/scripts/print_edition.py")

EVENT = json.loads((ROOT / "memo-setup" / "assets" / "events.json").read_text())["EV-PLOW"]
URL, KEY = EVENT["print_url"], EVENT["print_key"]
PRINTER = {"configured": True, "url": URL, "key": KEY, "paper": "72mm"}


def test_an_event_install_asks_only_for_its_connections(tmp_path, monkeypatch, capsys):
    # No hour, printer, Mac or time-zone question at the event: the first thing the
    # attendee sees is the Google/Slack connect links, and their "done" closes setup.
    monkeypatch.setenv("MEMO_EVENT", "ev-plow")
    config = str(tmp_path / "config.json")
    assert record.main(["record_setup.py", config, "owner.language=English"]) == 0
    draft = json.loads((tmp_path / ".setup-draft.json").read_text())
    assert draft["printer"] == PRINTER
    assert draft["mac"] == {"awake": False} and draft["event"] == "EV-PLOW" and draft["start"] == "01:00"
    assert "NEXT_QUESTION=connect" in capsys.readouterr().out
    assert record.main(["record_setup.py", config, "connected=true"]) == 0
    assert "NEXT_QUESTION=close" in capsys.readouterr().out


def test_without_an_event_the_interview_is_unchanged_and_an_unknown_code_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MEMO_EVENT", raising=False)
    assert record.main(["record_setup.py", str(tmp_path / "config.json"), "start=01:00"]) == 0
    assert "NEXT_QUESTION=printer" in capsys.readouterr().out
    monkeypatch.setenv("MEMO_EVENT", "EV-NOPE")
    assert record.main(["record_setup.py", str(tmp_path / "other" / "config.json"), "start=01:00"]) == 1


def test_finalize_runs_an_event_installs_first_memo_now_instead_of_the_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    (tmp_path / ".setup-draft.json").write_text(json.dumps({
        "start": "01:00", "event": "EV-PLOW", "mac": {"awake": False}, "connected": True,
        "printer": PRINTER}))
    backend = FakeScheduler()
    # No --owner-tz: an event install never asks for a city, it takes the event's zone.
    assert finalize.main(["finalize_setup.py", str(tmp_path / "config.json")], backend=backend) == 0
    config = json.loads((tmp_path / "config.json").read_text())
    assert config["owner"]["timezone"] == "America/Los_Angeles"
    assert config["printer"] == {**PRINTER, "name": None}
    # The event's short read (memo-tournament § Event), not the 240-minute tournament: the
    # receipt prints while its owner is still in the room.
    assert [j["name"] for j in backend.created] == ["memo-now"]
    job = backend.created[0]
    assert "§ Event" in job["prompt"] and "The window is 30 minutes" in job["prompt"]
    assert job["timeout"] < 240 * 60


@pytest.mark.parametrize("printer, ok", [
    ({"configured": True, "name": None, "url": URL}, True),
    ({"configured": True, "name": None, "url": "http://not-https.example/print"}, False),
    ({"configured": True, "name": None}, False),
])
def test_the_gate_accepts_a_print_url_in_place_of_a_cups_name(printer, ok):
    config = {"owner": {"timezone": "America/Los_Angeles"}, "printer": printer,
              "memo": {"start": "01:00", "window_minutes": 240, "max_usd": 100}}
    try:
        rejected = any("printer.name" in f for f in gate.gate(config))
    except gate.GateError:  # the gate's own refusal of a missing name
        rejected = True
    assert rejected != ok


def test_a_print_url_gets_the_receipt_and_never_lp(tmp_path, monkeypatch, capsys):
    (tmp_path / "edition.json").write_text(json.dumps({"date": "2026-10-06"}))
    (tmp_path / "edition.pdf").write_bytes(b"%PDF-1.4")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"printer": {**PRINTER, "name": None}}))
    sent = []
    monkeypatch.setattr(pe, "write_receipt", lambda pdf: "/run/receipt.pdf")
    monkeypatch.setattr(pe, "send_to_url", lambda pdf, url, key: sent.append((pdf, url, key)) or {"position": 1})
    monkeypatch.setattr(pe, "ship", lambda *a, **k: pytest.fail("an event install has no Mac to lp on"))
    pe.main([str(tmp_path / "edition.pdf"), str(config)])
    assert sent == [("/run/receipt.pdf", URL, KEY)]
    assert "page sent to the event printer (queue position 1)" in capsys.readouterr().out


def test_send_to_url_posts_the_receipt_with_the_event_key_and_names_a_refusal(tmp_path, monkeypatch):
    import io, urllib.error, urllib.request
    import owner_chat
    monkeypatch.setenv("PLOW_API_BASE", "https://api.example")
    monkeypatch.setenv("PLOW_AGENT_TOKEN", "tok")
    monkeypatch.setattr(owner_chat, "fetch_identity", lambda base, token: {"agent": {"uid": "agent-1"}, "line": {"uid": "ln_p7"}})
    pdf = tmp_path / "receipt.pdf"
    pdf.write_bytes(b"%PDF-1.7 receipt")
    seen = []

    class Answer(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def urlopen(request, timeout):
        seen.append(request)
        if len(seen) == 2:
            raise urllib.error.HTTPError(request.full_url, 503, "x", {}, io.BytesIO(b'{"reason": "the event printer is off"}'))
        return Answer(b'{"status": "queued", "position": 2}')
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert pe.send_to_url(str(pdf), URL, KEY) == {"status": "queued", "position": 2}
    request = seen[0]
    assert request.full_url == URL and request.data == b"%PDF-1.7 receipt" and request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {KEY}" and request.get_header("X-plow-agent") == "agent-1"
    with pytest.raises(SystemExit, match="refused the receipt: the event printer is off"):
        pe.send_to_url(str(pdf), URL, KEY)


def test_an_event_installs_first_turn_is_the_connect_question_not_the_hour(tmp_path, monkeypatch):
    # Live on Oak: with no draft the gate said DRAFT:none and the agent asked the start hour.
    gate = load_module("setup_needed", "memo-shared/scripts/setup_needed.py")
    config = tmp_path / "config.json"
    monkeypatch.delenv("MEMO_EVENT", raising=False)
    assert gate.draft_line(config) == "DRAFT:none"
    monkeypatch.setenv("MEMO_EVENT", "EV-PLOW")
    assert gate.draft_line(config) == "DRAFT:start,printer,awake"
    (tmp_path / ".setup-draft.json").write_text(json.dumps({"connected": True}))
    assert gate.draft_line(config) == "DRAFT:start,printer,awake,connected"
    assert not (tmp_path / ".setup-draft.json").read_text().count("event"), "the gate only reads"


def test_an_event_install_speaks_english_until_the_attendee_writes_otherwise(tmp_path, monkeypatch):
    # 10-06: the event setup recorded no language, the agent inferred Portuguese for an
    # English-speaking owner, and the receipts printed PRIMEIRO PASSO.
    gate = load_module("setup_needed", "memo-shared/scripts/setup_needed.py")
    config = tmp_path / "config.json"
    monkeypatch.setenv("MEMO_EVENT", "EV-PLOW")
    assert record.main(["record_setup.py", str(config), "connected=true"]) == 0
    assert gate.language_line(config) == "LANG:English"
    assert record.main(["record_setup.py", str(config), "owner.language=Portuguese"]) == 0
    assert gate.language_line(config) == "LANG:Portuguese", "the attendee's own language still wins"
