"""finalize_setup.py — the only way memo-setup writes pt/config.json.

Measured live (2026-09-16): the close step said "**Write**
/var/lib/plow/pt/config.json from the draft" and named no command, and no
script in the tree wrote that file. The run had every field it needed —
printer probed, timezone read — ran the gate against a file nobody had
created, got "not valid JSON" (the gate collapses OSError into that line)
and told the owner the setup "hit a configuration error". Nothing was wrong
with the data; the file was simply never written.
"""
from __future__ import annotations

import json

import pytest

from conftest import load_module

finalize = load_module("finalize_setup", "memo-setup/scripts/finalize_setup.py")

COMPLETE = {
    "start": "01:00",
    "printer": {"configured": True, "name": "virtual_printer_online"},
    "mac": {"awake": True},
}


class Proc:
    def __init__(self, returncode=0):
        self.returncode, self.stdout, self.stderr = returncode, "", ""


class FakeScheduler:
    """The scheduler as finalize sees it: list() and create()."""

    def __init__(self, fail=False):
        self.created, self.fail = [], fail

    def list(self):
        return [type("Job", (), {"name": j["name"]})() for j in self.created]

    def create(self, job):
        if not self.fail:
            self.created.append(job)
        return Proc(1 if self.fail else 0)

    def jobs(self):
        return self.created


def seed(tmp_path, draft=None):
    (tmp_path / ".setup-draft.json").write_text(
        json.dumps(COMPLETE if draft is None else draft), encoding="utf-8"
    )
    return tmp_path / "config.json"


def run(config, tz="America/Sao_Paulo", backend=None):
    return finalize.main(["finalize_setup.py", str(config), "--owner-tz", tz],
                         backend=backend if backend is not None else FakeScheduler())


class TestWritesAValidConfig:
    def test_writes_config_that_passes_the_gate(self, tmp_path, capsys):
        config = seed(tmp_path)
        rc = run(config)
        out = capsys.readouterr().out
        assert rc == 0, out
        written = json.loads(config.read_text())
        assert written["owner"]["timezone"] == "America/Sao_Paulo"
        assert written["memo"] == {"start": "01:00", "window_minutes": 240, "max_usd": 100}
        assert written["printer"] == {"configured": True, "name": "virtual_printer_online"}
        assert written["priority"] == {"configured": True}
        assert written["signals"] == {"group_chat": False, "email": False, "imessage": False}
        assert "delivery" not in written and "mail" not in written
        assert "CONFIG:written" in out and "memo.start=01:00 (America/Sao_Paulo)" in out

    def test_printer_not_configured_writes_null_name(self, tmp_path):
        config = seed(tmp_path, dict(COMPLETE, printer={"configured": False}))
        run(config)
        assert json.loads(config.read_text())["printer"] == {"configured": False, "name": None}

    def test_a_mac_that_may_sleep_still_finishes_setup(self, tmp_path):
        # The owner was told why it matters; their "no" is an answer, not a blocker.
        config = seed(tmp_path, dict(COMPLETE, mac={"awake": False}))
        assert run(config) == 0


class TestBootstrap:
    def test_finalize_schedules_the_bootstrap_once(self, tmp_path, capsys):
        backend = FakeScheduler()
        config = seed(tmp_path)
        assert run(config, backend=backend) == 0
        assert run(config, backend=backend) == 0
        assert [j["name"] for j in backend.jobs()].count("memo-bootstrap") == 1
        out = capsys.readouterr().out
        assert "queued: memo-bootstrap" in out and "already queued: memo-bootstrap" in out

    def test_a_bootstrap_that_already_ran_is_never_queued_again(self, tmp_path):
        # A one-shot leaves the listing once it ran; the marker remembers it.
        config = seed(tmp_path)
        run(config, backend=FakeScheduler())
        later = FakeScheduler()
        run(config, backend=later)
        assert later.jobs() == []

    def test_the_bootstrap_job_is_a_one_shot_a_minute_out(self, tmp_path):
        backend = FakeScheduler()
        run(seed(tmp_path), backend=backend)
        (job,) = backend.jobs()
        assert job["tz"] is None and "T" in job["schedule"]
        assert "§ Bootstrap" in job["prompt"] and "[PLOW_PAPER_RUN]" not in job["prompt"]

    def test_a_failed_queue_says_so_after_the_config_is_written(self, tmp_path, capsys):
        config = seed(tmp_path)
        assert run(config, backend=FakeScheduler(fail=True)) == 1
        assert config.exists()
        assert "could not queue memo-bootstrap" in capsys.readouterr().err
        assert not (tmp_path / "bootstrap.json").exists()


class TestRefusesRatherThanWriteGarbage:
    def test_refuses_an_unfinished_interview(self, tmp_path, capsys):
        config = seed(tmp_path, {"start": "01:00"})
        assert run(config) == 1
        assert not config.exists(), "a refused finalize must not leave a partial config"
        assert "printer" in capsys.readouterr().err

    def test_refuses_a_missing_draft_with_a_clear_message(self, tmp_path, capsys):
        assert run(tmp_path / "config.json") == 1
        err = capsys.readouterr().err
        assert "draft" in err and "not valid JSON" not in err

    def test_refuses_an_unknown_timezone(self, tmp_path):
        config = seed(tmp_path)
        assert run(config, tz="Mars/Olympus") == 1
        assert not config.exists()

    @pytest.mark.parametrize("draft, field", [
        (dict(COMPLETE, printer={"configured": True, "name": "   "}), "printer.name"),
        (dict(COMPLETE, start="1am"), "memo.start"),
    ])
    def test_reports_gate_failures_verbatim(self, tmp_path, capsys, draft, field):
        config = seed(tmp_path, draft)
        assert run(config) == 1
        assert field in capsys.readouterr().err
        assert not config.exists()


class TestCarriesTheLanguage:
    """owner.language is what a SCHEDULED run writes in. memo-intake keeps it
    current from live chat, but the first night can run before memo-intake
    ever does, so setup must plant it."""

    def test_writes_owner_language_from_the_draft(self, tmp_path):
        config = seed(tmp_path, dict(COMPLETE, owner={"language": "Portuguese"}))
        assert run(config) == 0
        assert json.loads(config.read_text())["owner"]["language"] == "Portuguese"

    def test_omits_the_key_when_unrecorded(self, tmp_path):
        config = seed(tmp_path)
        run(config)
        assert "language" not in json.loads(config.read_text())["owner"]
