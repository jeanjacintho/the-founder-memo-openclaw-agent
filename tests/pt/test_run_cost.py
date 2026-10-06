"""The memo prices every transcript usage call, including resumed sessions."""
import json
from datetime import datetime, timezone
import sqlite3
from types import SimpleNamespace

import pytest
from conftest import load_module

rc = load_module("run_cost", "memo-shared/scripts/run_cost.py")
PROVIDER = {"models": [{"id": "writer", "cost": {"input": 5, "output": 25}}]}


def event(response, stamp=100_000, **usage):
    return {"timestamp": datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat(), "message": {"role": "assistant", "responseId": response,
            "provider": "plow", "model": "writer", "usage": {"input": 1_000_000, "output": 0, **usage}}}


@pytest.fixture
def stores(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(tmp_path))
    # The real pinned decoder is exercised in the built-image Node test.
    monkeypatch.setattr(rc, "_client", lambda: SimpleNamespace(
        _event_json=lambda raw, blob, size: raw,
        _stamp_ms=lambda stamp, created: datetime.fromisoformat(stamp).timestamp() * 1000 if stamp else created))
    config = tmp_path / "provider.json"
    config.write_text(json.dumps(PROVIDER))
    monkeypatch.setattr(rc, "PROVIDER_CONFIG", str(config))
    monkeypatch.setattr(rc.time, "time", lambda: 120)

    def write(entries, agent="main", compressed=False):
        path = tmp_path / "agents" / agent / "agent" / "openclaw-agent.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            extra = ", event_zstd BLOB, event_utf8_bytes INTEGER" if compressed else ""
            db.execute(f"CREATE TABLE transcript_events (session_id TEXT, event_json TEXT, created_at INTEGER{extra})")
            db.executemany("INSERT INTO transcript_events (session_id, event_json, created_at) VALUES (?, ?, ?)",
                           [(session, json.dumps(e), 110_000) for session, e in entries])
        return path
    return write


def test_resumed_session_includes_every_call_and_stops_generation(stores, capsys):
    stores([("coordinator", event("generation-1")), ("coordinator", event("generation-2", input=2_000_000))])
    assert rc.main(["total", "--since-minutes", "1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"usd": 15, "sessions": 1, "unpriced": 0}
    assert rc.main(["can-start", "--spent", str(result["usd"]), "--longest", "5", "--max", "19"]) == 1


def test_minute_window_filters_event_time_and_checkpoint_copies(stores):
    stores([("same", event("old", stamp=10_000)), ("same", event("included")),
            ("same", event("future", stamp=150_000))])
    stores([("copy", event("included"))], agent="fork", compressed=True)
    assert rc.summary(rc.events(60_000, 120_000), rc.prices(PROVIDER)) == {"usd": 5, "sessions": 1, "unpriced": 0}


@pytest.mark.parametrize("change", [
    {"model": "unpriced"}, {"provider": "another-provider"},
    {"usage": {"input": 10}}, {"usage": {"input": 10, "output": 0, "cacheRead": 100}},
])
def test_partial_or_unpriced_usage_never_reports_a_smaller_total(stores, change):
    unknown = event("unknown")
    unknown["message"].update(change)
    stores([("priced", event("priced")), ("unknown", unknown)])
    assert rc.summary(rc.events(0, 120_000), rc.prices(PROVIDER)) == {"usd": None, "sessions": 2, "unpriced": 1}


def test_cached_tokens_use_their_explicit_model_prices(stores):
    stores([("cached", event("cached", cacheRead=1_000_000, cacheWrite=100_000))])
    provider = {"models": [{"id": "writer", "cost": {"input": 5, "output": 25, "cacheRead": 1, "cacheWrite": 6.25}}]}
    assert rc.summary(rc.events(0, 120_000), rc.prices(provider))["usd"] == pytest.approx(6.625)


def test_empty_store_is_unknown(stores, capsys):
    stores([])
    assert rc.main(["total", "--since-minutes", "1"]) == 0
    assert json.loads(capsys.readouterr().out) == {"usd": None, "sessions": 0, "unpriced": 0}


@pytest.mark.parametrize("failure", ["missing", "corrupt-json", "corrupt-db", "decode"])
def test_unreadable_usage_fails_without_a_partial_total(stores, capsys, monkeypatch, failure):
    if failure != "missing":
        path = stores([("s", event("r"))])
        if failure == "corrupt-db":
            path.write_text("not sqlite")
        elif failure == "corrupt-json":
            with sqlite3.connect(path) as db:
                db.execute("UPDATE transcript_events SET event_json = '{'")
        else:
            def refuse(*args):
                raise RuntimeError("cannot decode compressed usage")
            monkeypatch.setattr(rc, "_client", lambda: SimpleNamespace(_event_json=refuse))
    assert rc.main(["total", "--since-minutes", "1"]) == 1
    captured = capsys.readouterr()
    assert not captured.out and "run_cost:" in captured.err


@pytest.mark.parametrize("spent, longest, maximum, code", [
    (0.1, 0.2, 0.3, 0), (0.1, 0.20001, 0.3, 1), (10, 20, 100, 0), (80, 20, 100, 0), (85, 20, 100, 1), (100, 0, 100, 1), (0, 0, 0, 1), ("null", 20, 100, 1),
])
def test_cli_can_start_respects_the_ceiling(spent, longest, maximum, code):
    assert rc.main(["can-start", "--spent", str(spent), "--longest", str(longest), "--max", str(maximum)]) == code
