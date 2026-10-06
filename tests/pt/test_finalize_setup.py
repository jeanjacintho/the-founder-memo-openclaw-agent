"""finalize_setup.py — the only way memo-setup writes pt/config.json.

Measured live (2026-09-16): the close step said "**Write**
/var/lib/plow/pt/config.json from the draft" and named no command, and no
script in the tree wrote that file. The run had every field it needed —
printer probed, timezone read, topics saved — ran the gate against a file
nobody had created, got "not valid JSON" (the gate collapses OSError into
that line) and told the owner the setup "hit a configuration error". Nothing
was wrong with the data; the file was simply never written.
"""
from __future__ import annotations

import json

import pytest

from conftest import load_module

finalize = load_module("finalize_setup", "memo-setup/scripts/finalize_setup.py")

COMPLETE = {
    "local_hour": "07:00",
    "printer": {"configured": True, "name": "virtual_printer_online"},
    "priority": {"configured": False},
    "mail": {"configured": True},
    "news_asked": True,
    "signals": {"group_chat": False, "email": True, "imessage": False},
}


def seed(tmp_path, draft=None):
    (tmp_path / ".setup-draft.json").write_text(
        json.dumps(COMPLETE if draft is None else draft), encoding="utf-8"
    )
    return tmp_path / "config.json"


class TestWritesAValidConfig:
    def test_writes_config_that_passes_the_gate(self, tmp_path, capsys):
        config = seed(tmp_path)
        rc = finalize.main(
            ["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"]
        )
        out = capsys.readouterr().out
        assert rc == 0, out
        written = json.loads(config.read_text())
        assert written["owner"]["timezone"] == "America/Sao_Paulo"
        assert written["printer"] == {"configured": True, "name": "virtual_printer_online"}
        assert written["mail"]["configured"] is True
        assert written["signals"] == {"group_chat": False, "email": True, "imessage": False}
        assert "delivery" not in written
        assert written["memo"] == {"start": "07:00", "window_minutes": 240, "max_usd": 100}
        assert "memo.start=07:00" in out
        assert "CONFIG:written" in out

    @pytest.mark.parametrize("hour", ["07:00", "00:20", "23:30"])
    def test_chosen_start_and_opt_out_are_preserved(self, tmp_path, hour):
        config = seed(tmp_path, dict(COMPLETE, local_hour=hour, priority={"configured": False}))
        finalize.main(["finalize_setup.py", str(config), "--owner-tz", "UTC"])
        written = json.loads(config.read_text())
        assert written["memo"]["start"] == hour
        assert written["priority"]["configured"] is False

    @pytest.mark.parametrize("container_tz", ["UTC", "", "Asia/Tokyo"])
    def test_stores_the_hour_the_owner_named_whatever_the_container_clock(
            self, tmp_path, monkeypatch, container_tz):
        # register_crons.py converts at registration; the config holds the
        # owner's wall clock and no container-clock copy of it.
        monkeypatch.setenv("TZ", container_tz)
        config = seed(tmp_path)
        assert finalize.main(
            ["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"]) == 0
        written = json.loads(config.read_text())
        assert written["memo"]["start"] == "07:00"
        assert "local_hour" not in written["memo"]

    def test_printer_not_configured_writes_null_name(self, tmp_path):
        draft = dict(COMPLETE, printer={"configured": False})
        config = seed(tmp_path, draft)
        finalize.main(["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"])
        written = json.loads(config.read_text())
        assert written["printer"] == {"configured": False, "name": None}


class TestRefusesRatherThanWriteGarbage:
    def test_refuses_an_unfinished_interview(self, tmp_path, capsys):
        config = seed(tmp_path, {"local_hour": "07:00"})
        rc = finalize.main(
            ["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"]
        )
        assert rc == 1
        assert not config.exists(), "a refused finalize must not leave a partial config"
        assert "printer" in capsys.readouterr().err

    def test_refuses_a_missing_draft_with_a_clear_message(self, tmp_path, capsys):
        rc = finalize.main(
            ["finalize_setup.py", str(tmp_path / "config.json"), "--owner-tz", "America/Sao_Paulo"]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "draft" in err and "not valid JSON" not in err

    def test_refuses_an_unknown_timezone(self, tmp_path, capsys):
        config = seed(tmp_path)
        rc = finalize.main(["finalize_setup.py", str(config), "--owner-tz", "Mars/Olympus"])
        assert rc == 1
        assert not config.exists()

    def test_reports_gate_failures_verbatim(self, tmp_path, capsys):
        # A draft that is "complete" but carries a printer with no name is
        # exactly what gate check 4 refuses; finalize must surface that, not
        # claim success.
        draft = dict(COMPLETE, printer={"configured": True, "name": "   "})
        config = seed(tmp_path, draft)
        rc = finalize.main(
            ["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"]
        )
        assert rc == 1
        assert "printer.name" in capsys.readouterr().err


class TestCarriesTheLanguage:
    """owner.language is gate check 7 and what a SCHEDULED edition writes in.
    memo-intake keeps it current from live chat, but a paper can be delivered
    before memo-intake ever runs, so setup must plant it."""

    def test_writes_owner_language_from_the_draft(self, tmp_path):
        draft = dict(COMPLETE, owner={"language": "Portuguese"})
        config = seed(tmp_path, draft)
        rc = finalize.main(["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"])
        assert rc == 0
        assert json.loads(config.read_text())["owner"]["language"] == "Portuguese"

    def test_omits_the_key_when_unrecorded(self, tmp_path):
        # Gate check 7: absent is valid. An invented default is not.
        config = seed(tmp_path)
        finalize.main(["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"])
        assert "language" not in json.loads(config.read_text())["owner"]



def test_setup_choice_is_the_registered_start(tmp_path):
    crons = load_module("setup_crons", "memo-schedule/scripts/register_crons.py")
    config = seed(tmp_path, dict(COMPLETE, local_hour="23:30", priority={"configured": True}))
    assert finalize.main(["finalize_setup.py", str(config), "--owner-tz", "UTC"]) == 0
    start, window = crons.load_memo(config)
    assert crons.nightly_job(start, window, "UTC")["schedule"] == "30 23 * * *"
