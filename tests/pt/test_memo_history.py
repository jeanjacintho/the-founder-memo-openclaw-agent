"""history.py: the cards the memo printed lately, read back from the wiki."""
from __future__ import annotations

import json
from datetime import date

import pytest

from conftest import load_module
from wiki import MEMOS, Wiki, join_page

history = load_module("history", "memo-tournament/scripts/memo_history.py")
TODAY = date(2026, 9, 19)


def day_page(mac, day, card=None):
    path = mac.home / "Plow" / "wiki" / MEMOS / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"type": "Memo", "date": day, **({"priority": card} if card else {})}
    path.write_text(join_page(meta, f"# The Founder Memo, {day}\n"))


class TestRecent:
    def test_the_last_weeks_cards_oldest_first_without_the_empty_days(self, mac):
        day_page(mac, "2026-09-11", {"headline": "too old"})
        day_page(mac, "2026-09-12", {"headline": "Call Raj"})
        day_page(mac, "2026-09-15")  # a night with no card
        day_page(mac, "2026-09-18", {"headline": "Close the pilot"})
        assert history.recent(Wiki(mac.call_tool), TODAY) == [
            {"date": "2026-09-12", "desk": {"headline": "Call Raj"}},
            {"date": "2026-09-18", "desk": {"headline": "Close the pilot"}},
        ]

    def test_todays_own_edition_is_not_history(self, mac):
        # A second run on the same date must not read the first back as "yesterday".
        day_page(mac, "2026-09-18", {"headline": "Close the pilot"})
        day_page(mac, "2026-09-19", {"headline": "This morning's headline"})
        assert history.recent(Wiki(mac.call_tool), TODAY) == [
            {"date": "2026-09-18", "desk": {"headline": "Close the pilot"}},
        ]

    def test_only_todays_edition_is_no_history(self, mac):
        day_page(mac, "2026-09-19", {"headline": "This morning's headline"})
        assert history.recent(Wiki(mac.call_tool), TODAY) == []

    def test_no_pages_is_no_history(self, mac):
        assert history.recent(Wiki(mac.call_tool), TODAY) == []


class TestCli:
    def test_an_unreachable_mac_is_an_error(self, mac, monkeypatch):
        mac.asleep = True
        monkeypatch.setattr(history, "connect", lambda: Wiki(mac.call_tool))
        with pytest.raises(SystemExit) as exc:
            history.main(["recent"])
        assert str(exc.value).startswith("error: history unavailable — Mac unreachable")

    def test_a_bad_owner_timezone_is_an_error(self, mac, monkeypatch):
        # owner_time.owner_today()'s own refuse-instead-of-guess behavior is
        # tested in test_owner_time.py; this just proves main() surfaces
        # whatever it raises as the documented error, not a bare traceback.
        monkeypatch.setattr(history, "connect", lambda: Wiki(mac.call_tool))

        def bad_owner_today():
            raise KeyError("Not/AZone")

        monkeypatch.setattr(history, "owner_today", bad_owner_today)
        with pytest.raises(SystemExit) as exc:
            history.main(["recent"])
        assert str(exc.value).startswith("error: history unavailable — ")

    def test_the_cli_prints_the_cards(self, mac, monkeypatch, capsys):
        day_page(mac, "2026-09-18", {"headline": "Close the pilot"})
        monkeypatch.setattr(history, "connect", lambda: Wiki(mac.call_tool))
        monkeypatch.setattr(history, "owner_today", lambda: TODAY)
        history.main(["recent"])
        assert json.loads(capsys.readouterr().out) == [{"date": "2026-09-18", "desk": {"headline": "Close the pilot"}}]
