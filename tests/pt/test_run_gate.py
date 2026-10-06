"""run_gate.py -- the night waits for the owner's Mac, but never past its window."""
from __future__ import annotations

import pytest

from conftest import load_module

run_gate = load_module("run_gate", "memo-shared/scripts/run_gate.py")


def test_an_awake_mac_passes_at_once(mac, clock):
    assert run_gate.wait(mac.call_tool, started=clock.now(), window_minutes=240,
                         sleep=clock.advance, now=clock.now) == 0
    assert clock.elapsed == 0


def test_a_mac_without_a_wiki_yet_still_answered(mac, clock):
    # ENOENT is the Mac answering; setup's bootstrap creates the wiki itself.
    assert not (mac.home / "Plow/wiki/wiki.toml").exists()
    assert run_gate.wait(mac.call_tool, started=clock.now(), window_minutes=240,
                         sleep=clock.advance, now=clock.now) == 0


def test_gate_gives_up_when_the_window_closes(mac, clock):
    mac.asleep = True
    assert run_gate.wait(mac.call_tool, started=clock.now(), window_minutes=240,
                         sleep=clock.advance, now=clock.now) == 2
    assert clock.elapsed >= 240 * 60


def test_gate_passes_when_the_mac_wakes_late(mac, clock):
    mac.asleep = True
    clock.on_advance(lambda t: setattr(mac, "asleep", t < 30 * 60))
    assert run_gate.wait(mac.call_tool, started=clock.now(), window_minutes=240,
                         sleep=clock.advance, now=clock.now) == 0
    assert 30 * 60 <= clock.elapsed < 40 * 60


def test_one_call_never_outlasts_the_exec_timeout(mac, clock):
    # OpenClaw's exec ends a command at 30 minutes; the conductor calls again on 3.
    mac.asleep = True
    started = clock.now()
    assert run_gate.wait(mac.call_tool, started=started, window_minutes=240, sleep=clock.advance,
                         now=clock.now, max_wait_seconds=run_gate.MAX_WAIT_SECONDS) == 3
    assert clock.elapsed <= run_gate.MAX_WAIT_SECONDS < 30 * 60
    while (code := run_gate.wait(mac.call_tool, started=started, window_minutes=240, sleep=clock.advance,
                                 now=clock.now, max_wait_seconds=run_gate.MAX_WAIT_SECONDS)) == 3:
        pass
    assert code == 2


@pytest.mark.parametrize("asleep, code, line", [(False, 0, "MAC:reachable"), (True, 2, "MAC:window-closed")])
def test_cli_prints_its_answer(mac, clock, monkeypatch, capsys, asleep, code, line):
    mac.asleep = asleep
    monkeypatch.setattr(run_gate.time, "sleep", clock.advance)
    monkeypatch.setattr(run_gate, "_now", clock.now)
    started = (clock.now()).isoformat()
    assert run_gate.main(["wait", "--started", started, "--window", "10"], call_tool=mac.call_tool) == code
    assert capsys.readouterr().out.strip() == line


def test_an_awake_mac_after_the_window_cannot_start(mac, clock):
    started = clock.now()
    clock.advance(11 * 60)
    assert run_gate.wait(mac.call_tool, started, 10, now=clock.now) == 2


def test_sleep_stops_at_a_short_window_boundary(mac, clock):
    mac.asleep = True
    assert run_gate.wait(mac.call_tool, clock.now(), 1, sleep=clock.advance, now=clock.now) == 2
    assert clock.elapsed == 60
