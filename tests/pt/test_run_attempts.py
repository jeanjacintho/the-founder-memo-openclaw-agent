"""run_attempts.py -- a paper that keeps failing stops re-running all day."""
from __future__ import annotations

import contextlib
import io
from datetime import date

import pytest

from conftest import load_module

attempts = load_module("run_attempts", "pt-shared/scripts/run_attempts.py")


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
    return tmp_path / "pt"


def out(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = attempts.main(argv)
    return code, buf.getvalue().strip()


def test_the_first_attempts_proceed(pt_home):
    assert [out(["begin"])[1] for _ in range(attempts.MAX_ATTEMPTS)] == ["proceed"] * attempts.MAX_ATTEMPTS


def test_the_next_one_gives_up_and_only_the_first_give_up_asks_for_a_notice(pt_home):
    for _ in range(attempts.MAX_ATTEMPTS):
        out(["begin"])
    assert out(["begin"]) == (0, "give-up")
    assert out(["begin"]) == (0, "give-up-quiet")
    assert out(["begin"]) == (0, "give-up-quiet")


def test_a_delivered_edition_starts_the_count_over(pt_home):
    for _ in range(attempts.MAX_ATTEMPTS - 1):
        out(["begin"])
    assert out(["delivered"]) == (0, "cleared")
    assert [out(["begin"])[1] for _ in range(attempts.MAX_ATTEMPTS)] == ["proceed"] * attempts.MAX_ATTEMPTS


def test_delivered_without_a_count_is_not_an_error(pt_home):
    assert out(["delivered"]) == (0, "cleared")


def test_the_limit_is_a_flag(pt_home):
    assert out(["begin", "--max-attempts", "1"])[1] == "proceed"
    assert out(["begin", "--max-attempts", "1"])[1] == "give-up"


def test_a_new_owner_day_has_a_fresh_count_and_the_old_file_goes(pt_home, monkeypatch):
    for _ in range(attempts.MAX_ATTEMPTS):
        out(["begin"])
    yesterday = pt_home / f"paper-attempts-{date(2020, 1, 1).isoformat()}.json"
    yesterday.write_text('{"starts": 9, "told": true}')
    assert out(["begin"])[1] == "give-up"
    assert not yesterday.exists()


def test_an_unreadable_count_is_a_fresh_one(pt_home):
    pt_home.mkdir(parents=True)
    (pt_home / f"paper-attempts-{attempts.owner_now().date().isoformat()}.json").write_text("not json")
    assert out(["begin"])[1] == "proceed"
