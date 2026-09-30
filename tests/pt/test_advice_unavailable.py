"""advice_unavailable.py: the advice desk may print "unavailable" only with proof."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

from conftest import load_module

adv = load_module("advice_unavailable", "pt-priority/scripts/advice_unavailable.py")

DAY = "2026-09-30"
TZ = "America/Sao_Paulo"
BRT = timezone(timedelta(hours=-3))


def ms(hour, minute, day=30):
    return int(datetime(2026, 9, day, hour, minute, tzinfo=BRT).timestamp() * 1000)


def subagent(started_ms):
    return {"key": "agent:main:subagent:abc", "sessionStartedAt": started_ms}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """PT_HOME with the owner's config and a lock this paper took at 07:00:14."""
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"owner": {"timezone": TZ}}))
    run = tmp_path / "run"
    run.mkdir()
    (run / f"paper-workspace-{DAY}.lock").write_text("2026-09-30T07:00:14-03:00\n")
    monkeypatch.setattr(adv, "today", lambda: DAY)
    return tmp_path


def notes(home):
    return json.loads((home / "run" / "desk-priority" / "notes.json").read_text())


class TestWindow:
    # Measured live 2026-09-30: the 07:00 paper had 148 minutes to 09:30 and
    # printed "advice unavailable" without starting a single critic.
    def test_a_morning_paper_with_its_full_window_may_not_skip(self, home, capsys):
        with pytest.raises(SystemExit) as exc:
            adv.main(["window", "--deliver-at", "09:30", "--reason", "sem tempo"])
        assert "149 minutes" in str(exc.value) and "run the tournament" in str(exc.value)
        assert not (home / "run" / "desk-priority" / "notes.json").exists()

    def test_a_paper_that_took_the_lock_after_its_hour_records_why(self, home):
        (home / "run" / f"paper-workspace-{DAY}.lock").write_text("2026-09-30T13:13:00-03:00\n")
        adv.main(["window", "--deliver-at", "09:30", "--reason", "a entrega já tinha passado"])
        assert notes(home) == {
            "date": DAY, "could_not_source": ["a entrega já tinha passado"],
            "skip": {"kind": "window", "deliver_at": "09:30", "minutes": -223}}

    def test_without_the_lock_there_is_no_window_to_measure(self, home):
        (home / "run" / f"paper-workspace-{DAY}.lock").unlink()
        with pytest.raises(SystemExit, match="does not hold today's paper-workspace lock"):
            adv.main(["window", "--deliver-at", "09:30", "--reason", "x"])


class TestFailed:
    def test_a_tournament_that_never_started_cannot_have_failed(self, home, monkeypatch):
        monkeypatch.setattr(adv, "list_sessions", lambda: [subagent(ms(7, 5, day=29))])
        with pytest.raises(SystemExit, match="no tournament child has started"):
            adv.main(["failed", "--reason", "não foi possível validar as três gerações"])

    def test_a_tournament_that_ran_records_how_many_children_it_started(self, home, monkeypatch):
        monkeypatch.setattr(adv, "list_sessions", lambda: [subagent(ms(7, 10)), subagent(ms(7, 30)),
                                                           {"key": "agent:main:main", "sessionStartedAt": ms(7, 20)}])
        adv.main(["failed", "--reason", "a terceira geração não passou no gate"])
        assert notes(home)["skip"] == {"kind": "failed", "children": 2}


class TestBlocked:
    def test_a_reachable_wiki_is_not_a_blocked_desk(self, home, monkeypatch):
        monkeypatch.setattr(adv, "wiki_check", lambda: (0, "WIKI:ready"))
        with pytest.raises(SystemExit, match="wiki_setup.py --desk succeeded"):
            adv.main(["blocked", "--reason", "o wiki não respondeu"])

    def test_an_unreachable_wiki_records_the_check_that_failed(self, home, monkeypatch):
        monkeypatch.setattr(adv, "wiki_check", lambda: (1, "error: wiki not ready — Mac unreachable"))
        adv.main(["blocked", "--reason", "o Mac não respondeu"])
        assert notes(home)["skip"] == {"kind": "blocked",
                                       "check": "error: wiki not ready — Mac unreachable"}


class TestListSessions:
    # Measured live 2026-09-30: `openclaw sessions list --json` prints the whole
    # listing at once, then its process never exits; waiting for the exit
    # timed out and threw the listing away.
    def test_a_listing_is_read_even_when_the_cli_never_exits(self, monkeypatch):
        listing = json.dumps({"count": 1, "sessions": [subagent(ms(7, 10))]})
        script = f"import sys, time; sys.stdout.write({listing!r} + chr(10)); sys.stdout.flush(); time.sleep(30)"
        monkeypatch.setattr(adv, "SESSIONS_ARGV", [sys.executable, "-c", script])
        started = time.monotonic()
        assert adv.list_sessions() == [subagent(ms(7, 10))]
        assert time.monotonic() - started < 10

    def test_a_cli_that_prints_nothing_is_no_listing(self, monkeypatch):
        monkeypatch.setattr(adv, "SESSIONS_ARGV", [sys.executable, "-c", "print('not json')"])
        assert adv.list_sessions() is None


class TestProof:
    """What render_edition.py re-checks before printing an unavailable card."""

    def run_root(self, home):
        return home / "run"

    def test_notes_written_by_hand_are_refused(self, home):
        problem = adv.proof_problem({"date": DAY, "could_not_source": ["x"]},
                                    self.run_root(home), DAY, TZ, lambda: [])
        assert "not written by advice_unavailable.py" in problem

    def test_a_window_skip_is_rechecked_against_the_lock(self, home):
        skip = {"kind": "window", "deliver_at": "09:30", "minutes": 10}
        problem = adv.proof_problem({"skip": skip}, self.run_root(home), DAY, TZ, lambda: [])
        assert "149 minutes" in problem

    def test_a_failed_skip_is_rechecked_against_the_sessions(self, home):
        problem = adv.proof_problem({"skip": {"kind": "failed", "children": 3}},
                                    self.run_root(home), DAY, TZ, lambda: [])
        assert "no tournament child has started" in problem
        assert adv.proof_problem({"skip": {"kind": "failed", "children": 1}}, self.run_root(home),
                                 DAY, TZ, lambda: [subagent(ms(7, 10))]) is None

    def test_sessions_that_cannot_be_listed_never_block_the_paper(self, home):
        assert adv.proof_problem({"skip": {"kind": "failed", "children": 1}},
                                 self.run_root(home), DAY, TZ, lambda: None) is None

    def test_a_blocked_skip_carries_its_failed_check(self, home):
        assert adv.proof_problem({"skip": {"kind": "blocked", "check": "error: Mac unreachable"}},
                                 self.run_root(home), DAY, TZ, lambda: []) is None
        assert "no failed check" in adv.proof_problem({"skip": {"kind": "blocked", "check": ""}},
                                                      self.run_root(home), DAY, TZ, lambda: [])
