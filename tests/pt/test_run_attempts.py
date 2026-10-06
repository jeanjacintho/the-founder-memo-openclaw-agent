"""run_attempts.py -- a paper that keeps failing stops re-running all day."""
from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from conftest import ROOT, load_module

attempts = load_module("run_attempts", "memo-shared/scripts/run_attempts.py")


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
    return tmp_path / "pt"


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    class Clock:
        now = datetime(2026, 10, 6, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(attempts, "owner_now", lambda: Clock.now)
    monkeypatch.setattr(attempts, "owner_today", lambda: Clock.now.date())
    return Clock


def run(command, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert attempts.main([command, *args]) == 0
    return buf.getvalue().strip()


def test_the_first_attempts_proceed(pt_home, clock):
    for _ in range(attempts.MAX_ATTEMPTS):
        assert run("begin") == "proceed"
        clock.now += timedelta(hours=4)


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


def spend_the_day(clock):
    for n in range(attempts.MAX_ATTEMPTS):
        assert run("begin") == "proceed"
        if n + 1 < attempts.MAX_ATTEMPTS:
            clock.now += timedelta(hours=4)


def test_the_next_start_tells_the_owner_once_in_the_same_call_and_stays_quiet_after(pt_home, chat, clock):
    spend_the_day(clock)
    assert run("begin") == "stop"
    assert [run("begin"), run("begin")] == ["stop", "stop"]
    assert chat.posts == ["The edition was not delivered after repeated attempts, so I am not trying again now. Ask me again later."]


def test_the_notice_speaks_the_owners_language_and_says_the_next_paper_comes_on_its_own(pt_home, chat, clock):
    pt_home.mkdir(parents=True)
    (pt_home / "config.json").write_text('{"owner": {"language": "Português"}}')
    spend_the_day(clock)
    assert run("begin", "--scheduled") == "stop"
    assert chat.posts == ["A edição não foi entregue depois de várias tentativas, então não vou tentar de novo agora. O próximo jornal agendado sai amanhã."]


def test_a_topic_edition_has_its_own_count_apart_from_the_papers(pt_home, chat, clock):
    clock.now = clock.now.replace(hour=0)
    spend_the_day(clock)
    assert run("begin") == "stop"
    # The papers' day is spent; a topic's is not, and a spent topic does not touch the papers'.
    for _ in range(attempts.MAX_ATTEMPTS):
        assert run("begin", "--key", "t_9f2a") == "proceed"
        clock.now += timedelta(hours=4)
    assert run("begin", "--key", "t_9f2a", "--scheduled") == "stop"
    assert len(chat.posts) == 2, "each spent count tells the owner once"
    attempts.clear("t_9f2a")
    assert run("begin", "--key", "t_9f2a") == "proceed"
    assert run("begin") == "stop", "clearing the topic did not clear the papers"


def test_an_attempts_key_cannot_name_a_path(pt_home, chat, clock):
    with pytest.raises(SystemExit, match="not allowed"):
        run("begin", "--key", "../escape")


def test_simultaneous_starts_count_each_once(pt_home, chat, clock):
    # Topic jobs hold no workspace lock, so two of one key can start together.
    import subprocess

    from conftest import ROOT

    script = ROOT / "memo-shared" / "scripts" / "run_attempts.py"
    env = {**__import__("os").environ, "PT_HOME": str(pt_home)}
    code = f"import sys; sys.path.insert(0, {str(script.parent)!r}); import run_attempts as a; a.post_owner_text = lambda text: None; a.begin('t_race')"
    procs = [subprocess.Popen([sys.executable, "-c", code], env=env,
                              stdout=subprocess.PIPE, text=True) for _ in range(attempts.MAX_ATTEMPTS)]
    assert sorted(p.communicate()[0].strip() for p in procs) == ["proceed", "stop", "stop"]
    assert json.loads(next(pt_home.glob("paper-attempts-*-t_race.json")).read_text())["starts"] == 1


def test_a_failed_post_leaves_the_owner_untold_so_the_next_start_tries_again(pt_home, chat, capsys, clock):
    spend_the_day(clock)
    chat.fails = True
    assert [run("begin"), run("begin")] == ["stop-untold", "stop-untold"]
    assert "was not posted" in capsys.readouterr().err
    chat.fails = False
    assert run("begin") == "stop"
    assert run("begin") == "stop"
    assert len(chat.posts) == 1


def test_a_confirmed_delivery_starts_the_day_over(pt_home, clock):
    spend_the_day(clock)
    attempts.clear()
    assert run("begin") == "proceed"


def test_clearing_without_a_count_is_not_an_error(pt_home):
    attempts.clear()


def test_the_count_is_the_owner_days(pt_home, monkeypatch, clock):
    spend_the_day(clock)
    from datetime import date
    monkeypatch.setattr(attempts, "owner_today", lambda: date(2030, 1, 1))
    assert run("begin") == "proceed"


def test_backoff_grows_and_checks_do_not_spend_attempts(pt_home, chat, clock):
    assert run("begin") == "proceed"
    clock.now += timedelta(hours=1)
    assert run("begin") == "stop"
    assert run("begin") == "stop"
    assert len(chat.posts) == 1
    assert "2026-10-06 10:00 UTC" in chat.posts[0]
    clock.now += timedelta(hours=1)
    assert run("begin") == "proceed"
    clock.now += timedelta(hours=2)
    assert run("begin") == "stop"
    assert len(chat.posts) == 2
    assert "2026-10-06 14:00 UTC" in chat.posts[1]
    clock.now += timedelta(hours=2)
    assert run("begin") == "proceed"
    assert run("begin") == "stop"


def test_failed_cooldown_notice_is_retried_without_admitting_research(pt_home, chat):
    assert run("begin") == "proceed"
    chat.fails = True
    assert run("begin") == "stop-untold"
    chat.fails = False
    assert run("begin") == "stop"
    assert len(chat.posts) == 1
    attempts.clear()
    assert run("begin") == "proceed"


def test_old_counter_keeps_its_count_and_gains_backoff(pt_home, chat):
    pt_home.mkdir(parents=True)
    attempts._path().write_text('{"starts": 1, "told": false}')
    assert run("begin") == "proceed"
    assert run("begin") == "stop"
    assert json.loads(attempts._path().read_text())["starts"] == 2


def test_cooldown_notice_uses_the_owners_clock_and_language(pt_home, chat, clock):
    from zoneinfo import ZoneInfo
    pt_home.mkdir(parents=True)
    (pt_home / "config.json").write_text('{"owner": {"language": "Português"}}')
    clock.now = clock.now.astimezone(ZoneInfo("America/Sao_Paulo"))
    assert run("begin") == "proceed"
    assert run("begin") == "stop"
    assert chat.posts == ["A edição ainda não chegou. Vou pausar as tentativas até pelo menos 2026-10-06 07:00 -03; a entrega não está confirmada."]


@pytest.mark.parametrize("start", ["2026-03-08T01:30", "2026-11-01T00:30"])
def test_retry_waits_two_elapsed_hours_across_dst(pt_home, chat, clock, start):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("America/New_York")
    clock.now = datetime.fromisoformat(start).replace(tzinfo=zone)
    instant = clock.now.astimezone(timezone.utc)
    assert run("begin") == "proceed"
    retry_at = datetime.fromisoformat(json.loads(attempts._path().read_text())["retry_at"])
    assert retry_at == instant + timedelta(hours=2)
    clock.now = (instant + timedelta(hours=2, seconds=-1)).astimezone(zone)
    assert run("begin") == "stop"
    assert retry_at.astimezone(zone).strftime("%Y-%m-%d %H:%M %Z") in chat.posts[0]
    clock.now = (instant + timedelta(hours=2)).astimezone(zone)
    assert run("begin") == "proceed"


@pytest.mark.parametrize("starts,notice", [(1, "2026-10-06 12:00 UTC"), (3, "Ask me again later.")])
def test_owner_grant_admits_once(pt_home, chat, clock, starts, notice):
    assert run("begin") == "proceed"
    for _ in range(starts - 1):
        clock.now += timedelta(hours=4)
        assert run("begin") == "proceed"
    assert run("begin") == "stop"
    attempts.grant()
    assert run("begin", "--key", "topic") == "proceed"
    assert run("begin") == "proceed"
    assert run("begin") == "stop"
    assert len(chat.posts) == 2
    assert notice in chat.posts[-1]
    assert json.loads(attempts._path().read_text())["starts"] == starts + 1


def test_existing_translation_is_refreshed_before_a_cooldown_notice(pt_home, chat):
    import owner_phrases as phrases
    pt_home.mkdir(parents=True)
    (pt_home / "config.json").write_text('{"owner": {"language": "Español"}}')
    old = {key: "ES " + text for key, text in phrases.SOURCE.items() if key != "attempts.cooldown"}
    phrases.phrases_file().write_text(json.dumps({"language": "Español", "phrases": old}))
    assert phrases.status() == "missing"
    translation = {**old, "attempts.cooldown": "La edición no llegó. Pauso los intentos hasta {time}; la entrega no está confirmada."}
    phrases.record(json.dumps({"phrases": translation}))
    assert phrases.status() == "ready"
    assert run("begin") == "proceed"
    assert run("begin") == "stop"
    assert chat.posts == [translation["attempts.cooldown"].format(time="2026-10-06 10:00 UTC")]
    start = (ROOT / "memo-tournament/SKILL.md").read_text().split("## Start", 1)[1].split("## ", 1)[0]
    assert start.index("owner_phrases.py status") < start.index("owner_phrases.py template") < start.index("owner_phrases.py record") < start.index("run_attempts.py begin")
    assert "release --name paper-workspace" in start and "stop without research or waiting" in start


@pytest.mark.parametrize("starts", [1, 2])
@pytest.mark.parametrize("key", ["paper", "topic"])
def test_midnight_keeps_active_cooldown_but_resets_daily_starts(pt_home, chat, clock, starts, key):
    clock.now = datetime(2026, 10, 6, 23, 30, tzinfo=timezone.utc) - timedelta(hours=4 * (starts - 1))
    for _ in range(starts):
        assert run("begin", "--key", key) == "proceed"
        if _ + 1 < starts:
            clock.now += timedelta(hours=4)
    deadline = clock.now + timedelta(hours=2 * starts)
    assert run("begin", "--key", key) == "stop"
    clock.now = datetime(2026, 10, 7, 0, 5, tzinfo=timezone.utc)
    assert run("begin", "--key", key) == "stop"
    assert json.loads(attempts._path(key).read_text())["starts"] == 0
    assert len(chat.posts) == 1, "the same blocked interval does not repeat its notice"
    assert run("begin", "--key", "other") == "proceed"
    clock.now = deadline
    assert run("begin", "--key", key) == "proceed"
    assert json.loads(attempts._path(key).read_text())["starts"] == 1


@pytest.mark.parametrize("key", ["paper", "topic"])
@pytest.mark.parametrize("check_before_delivery", [False, True])
def test_delivery_after_midnight_clears_the_previous_days_cooldown(pt_home, chat, clock, key, check_before_delivery):
    clock.now = datetime(2026, 10, 6, 23, 30, tzinfo=timezone.utc)
    assert run("begin", "--key", key) == "proceed"
    clock.now += timedelta(hours=1)
    if check_before_delivery:
        assert run("begin", "--key", key) == "stop"
    attempts.clear(key)
    assert run("begin", "--key", key) == "proceed"
