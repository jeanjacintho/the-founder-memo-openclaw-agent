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


def run(command, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert attempts.main([command, *args]) == 0
    return buf.getvalue().strip()


def test_the_first_attempts_proceed(pt_home):
    assert [run("begin") for _ in range(attempts.MAX_ATTEMPTS)] == ["proceed"] * attempts.MAX_ATTEMPTS


@pytest.fixture
def chat(monkeypatch):
    """The owner's chat: records what begin posts; set .fails to make the post fail."""
    class Chat:
        posts, fails = [], False

    Chat.posts = []

    def post_owner_text(text):
        if Chat.fails:
            raise SystemExit("error: Plow Chat HTTP 503")
        Chat.posts.append(text)

    monkeypatch.setattr(attempts, "post_owner_text", post_owner_text)
    return Chat


def spend_the_day():
    for _ in range(attempts.MAX_ATTEMPTS):
        assert run("begin") == "proceed"


def test_the_next_start_tells_the_owner_once_in_the_same_call_and_stays_quiet_after(pt_home, chat):
    spend_the_day()
    assert run("begin") == "stop"
    assert [run("begin"), run("begin")] == ["stop", "stop"]
    assert chat.posts == ["The edition was not delivered after repeated attempts, so I am not trying again now. Ask me again later."]


def test_the_notice_says_when_the_next_paper_is_and_speaks_the_owners_language(pt_home, chat):
    (pt_home).mkdir(parents=True)
    (pt_home / "config.json").write_text('{"owner": {"language": "Português"}}')
    spend_the_day()
    assert run("begin", "--next-paper", "07:00") == "stop"
    assert chat.posts == ["A edição não foi entregue depois de várias tentativas, então não vou tentar de novo agora. O próximo jornal agendado sai amanhã às 07:00."]


def test_a_failed_post_leaves_the_owner_untold_so_the_next_start_tries_again(pt_home, chat, capsys):
    spend_the_day()
    chat.fails = True
    assert [run("begin"), run("begin")] == ["stop-untold", "stop-untold"]
    assert "was not posted" in capsys.readouterr().err
    chat.fails = False
    assert run("begin") == "stop"
    assert run("begin") == "stop"
    assert len(chat.posts) == 1


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
