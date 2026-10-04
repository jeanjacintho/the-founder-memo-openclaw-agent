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


@pytest.fixture
def chat(monkeypatch):
    """The owner's chat: records what notify posts; set .fails to make the post fail."""
    import bearer_http
    import post_to_chat

    class Chat:
        posts, fails = [], False

    Chat.posts = []
    monkeypatch.setattr(post_to_chat, "resolve_chat", lambda: ("https://plow.example", "cht_owner", "tok"))

    def post_json(base, path, token, label, payload):
        if Chat.fails:
            raise SystemExit("error: Plow Chat HTTP 503")
        Chat.posts.append((base, path, payload))

    monkeypatch.setattr(bearer_http, "post_json", post_json)
    return Chat


def notify(text="Not delivered; not trying again now."):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert attempts.main(["notify", "--text", text]) == 0
    return buf.getvalue().strip()


def test_the_next_one_gives_up_and_stays_quiet_only_once_the_owner_was_told(pt_home, chat):
    for _ in range(attempts.MAX_ATTEMPTS):
        run("begin")
    assert run("begin") == "give-up"
    assert notify() == "told"
    assert chat.posts == [("https://plow.example", "/v1/chats/cht_owner/messages", {"body": "Not delivered; not trying again now."})]
    assert [run("begin"), run("begin")] == ["give-up-quiet", "give-up-quiet"]


def test_a_failed_post_leaves_the_owner_untold_so_the_next_start_tries_again(pt_home, chat):
    for _ in range(attempts.MAX_ATTEMPTS):
        run("begin")
    chat.fails = True
    with pytest.raises(SystemExit, match="503"):
        notify()
    assert [run("begin"), run("begin")] == ["give-up", "give-up"]
    chat.fails = False
    assert notify() == "told"
    assert run("begin") == "give-up-quiet"


def test_notify_needs_a_message(pt_home, chat):
    with pytest.raises(SystemExit, match="needs the message text"):
        notify("  ")
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
