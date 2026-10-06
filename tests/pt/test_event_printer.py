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

LINE = json.loads((ROOT / "memo-setup" / "assets" / "events.json").read_text())["EV-PLOW"]["printer_line"]


def test_an_event_install_never_asks_about_a_printer_or_a_mac(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMO_EVENT", "ev-plow")
    assert record.main(["record_setup.py", str(tmp_path / "config.json"), "start=01:00"]) == 0
    draft = json.loads((tmp_path / ".setup-draft.json").read_text())
    assert draft["printer"] == {"configured": True, "line": LINE, "paper": "72mm"}
    assert draft["mac"] == {"awake": False} and draft["event"] == "EV-PLOW"
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
        "start": "01:00", "event": "EV-PLOW", "mac": {"awake": False},
        "printer": {"configured": True, "line": LINE, "paper": "72mm"}}))
    backend = FakeScheduler()
    assert finalize.main(["finalize_setup.py", str(tmp_path / "config.json"), "--owner-tz", "America/Los_Angeles"],
                         backend=backend) == 0
    config = json.loads((tmp_path / "config.json").read_text())
    assert config["printer"] == {"configured": True, "name": None, "line": LINE, "paper": "72mm"}
    assert [j["name"] for j in backend.created] == ["memo-now"]


@pytest.mark.parametrize("printer, ok", [
    ({"configured": True, "name": None, "line": LINE}, True),
    ({"configured": True, "name": None, "line": "1650 not e164"}, False),
    ({"configured": True, "name": None}, False),
])
def test_the_gate_accepts_a_printer_line_in_place_of_a_cups_name(printer, ok):
    config = {"owner": {"timezone": "America/Los_Angeles"}, "printer": printer,
              "memo": {"start": "01:00", "window_minutes": 240, "max_usd": 100}}
    try:
        rejected = any("printer.name" in f for f in gate.gate(config))
    except gate.GateError:  # the gate's own refusal of a missing name
        rejected = True
    assert rejected != ok


def test_a_printer_line_gets_the_receipt_and_never_lp(tmp_path, monkeypatch, capsys):
    (tmp_path / "edition.json").write_text(json.dumps({"date": "2026-10-06"}))
    (tmp_path / "edition.pdf").write_bytes(b"%PDF-1.4")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"printer": {"configured": True, "name": None, "line": LINE, "paper": "72mm"}}))
    sent = []
    monkeypatch.setattr(pe, "write_receipt", lambda pdf: "/run/receipt.pdf")
    monkeypatch.setattr(pe, "send_to_line", lambda pdf, line, date: sent.append((pdf, line, date)))
    monkeypatch.setattr(pe, "ship", lambda *a, **k: pytest.fail("an event install has no Mac to lp on"))
    pe.main([str(tmp_path / "edition.pdf"), str(config)])
    assert sent == [("/run/receipt.pdf", LINE, "2026-10-06")]
    assert "page sent to the event printer" in capsys.readouterr().out


def test_send_to_line_always_resolves_a_chat_with_only_the_printer_line(monkeypatch):
    # Review of #98: reusing any chat that merely contains the printer line could post a
    # receipt into a group with other people in it.
    import bearer_http, owner_chat, post_to_chat
    monkeypatch.setenv("PLOW_API_BASE", "https://api.example")
    monkeypatch.setenv("PLOW_AGENT_TOKEN", "tok")
    group = {"uid": "cht_group", "participants": [{"provider_key": LINE}, {"provider_key": "+15550100001"}]}
    monkeypatch.setattr(owner_chat, "fetch_identity", lambda base, token: {"line": {"uid": "ln_x"}, "chats": [group]})
    calls = []
    monkeypatch.setattr(bearer_http, "post_json_read", lambda base, path, token, label, body: calls.append((path, body)) or {"uid": "cht_printer"})
    monkeypatch.setattr(bearer_http, "post_json", lambda base, path, token, label, body: calls.append((path, body)))
    monkeypatch.setattr(post_to_chat, "declare_and_upload", lambda base, chat, token, pdf, filename=None: f"att@{chat}")
    pe.send_to_line("/run/receipt.pdf", LINE, "2026-10-06")
    assert calls[0] == ("/v1/chats", {"line_uid": "ln_x", "members": [LINE], "body": "The Founder Memo",
                                      "trusted": False, "idempotency_key": f"memo-print-{LINE}"})
    assert calls[-1] == ("/v1/chats/cht_printer/messages", {"body": "", "attachment_uids": ["att@cht_printer"]})
