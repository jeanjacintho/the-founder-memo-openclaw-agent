"""run_attempts.py -- a paper that keeps failing stops re-running all day."""
from __future__ import annotations

import contextlib
import io

import pytest

from conftest import load_module

attempts = load_module("run_attempts", "pt-shared/scripts/run_attempts.py")


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
    return tmp_path / "pt"


def run(command):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert attempts.main([command]) == 0
    return buf.getvalue().strip()


def test_the_first_attempts_proceed(pt_home):
    assert [run("begin") for _ in range(attempts.MAX_ATTEMPTS)] == ["proceed"] * attempts.MAX_ATTEMPTS


def test_the_next_one_gives_up_and_stays_quiet_only_once_the_owner_was_told(pt_home):
    for _ in range(attempts.MAX_ATTEMPTS):
        run("begin")
    assert run("begin") == "give-up"
    assert run("told") == "told"
    assert [run("begin"), run("begin")] == ["give-up-quiet", "give-up-quiet"]


def test_a_failed_notice_leaves_the_owner_untold_so_the_next_start_tries_again(pt_home):
    for _ in range(attempts.MAX_ATTEMPTS):
        run("begin")
    assert [run("begin"), run("begin"), run("begin")] == ["give-up"] * 3


def test_a_confirmed_delivery_starts_the_day_over(pt_home):
    for _ in range(attempts.MAX_ATTEMPTS):
        run("begin")
    attempts.clear()
    assert run("begin") == "proceed"


def test_clearing_without_a_count_is_not_an_error(pt_home):
    attempts.clear()


def test_the_count_is_the_owner_days(pt_home, monkeypatch):
    for _ in range(attempts.MAX_ATTEMPTS):
        run("begin")
    from datetime import date
    monkeypatch.setattr(attempts, "owner_today", lambda: date(2030, 1, 1))
    assert run("begin") == "proceed"
