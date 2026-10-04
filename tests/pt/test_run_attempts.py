"""run_attempts.py -- a paper that keeps failing stops re-running all day."""
from __future__ import annotations

import contextlib
import io
import sys

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


@pytest.fixture
def chat(monkeypatch):
    """The owner's chat: records what notify posts; set .fails to make the post fail."""
    class Chat:
        posts, fails = [], False

    Chat.posts = []

    def post_owner_text(text):
        if Chat.fails:
            raise SystemExit("error: Plow Chat HTTP 503")
        Chat.posts.append(text)

    monkeypatch.setattr(attempts, "post_owner_text", post_owner_text)
    return Chat


def notify(monkeypatch, text="Not delivered; not trying again now."):
    monkeypatch.setattr(sys, "stdin", io.StringIO(text + "\n"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert attempts.main(["notify"]) == 0
    return buf.getvalue().strip()


def test_the_next_one_gives_up_and_stays_quiet_only_once_the_owner_was_told(pt_home, chat, monkeypatch):
    for _ in range(attempts.MAX_ATTEMPTS):
        run("begin")
    assert run("begin") == "give-up"
    assert notify(monkeypatch) == "told"
    assert chat.posts == ["Not delivered; not trying again now."]
    assert [run("begin"), run("begin")] == ["give-up-quiet", "give-up-quiet"]


def test_a_failed_post_leaves_the_owner_untold_so_the_next_start_tries_again(pt_home, chat, monkeypatch):
    for _ in range(attempts.MAX_ATTEMPTS):
        run("begin")
    chat.fails = True
    with pytest.raises(SystemExit, match="503"):
        notify(monkeypatch)
    assert [run("begin"), run("begin")] == ["give-up", "give-up"]
    chat.fails = False
    assert notify(monkeypatch) == "told"
    assert run("begin") == "give-up-quiet"


def test_the_message_arrives_verbatim_on_stdin_whatever_it_contains(pt_home, chat, monkeypatch):
    # Model-written text never rides in an argument, where a shell would evaluate it.
    nasty = "Não entregue: \"$(touch pwned)\" `id` $HOME 'x'"
    assert notify(monkeypatch, nasty) == "told"
    assert chat.posts == [nasty]


def test_notify_needs_a_message(pt_home, chat, monkeypatch):
    with pytest.raises(SystemExit, match="needs the message text"):
        notify(monkeypatch, "  ")
    assert chat.posts == []


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
