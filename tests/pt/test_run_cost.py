"""run_cost.py -- what tonight's run has spent, priced from the install's own config."""
from __future__ import annotations

import json
import pathlib

import pytest

from conftest import load_module

rc = load_module("run_cost", "memo-shared/scripts/run_cost.py")
FIX = json.loads((pathlib.Path(__file__).parent / "fixtures/openclaw-sessions.json").read_text())
# The plow provider block boot writes to /etc/plow/openclaw/plow-provider.json5 (Sol unpriced).
PROVIDER = {"models": [
    {"id": "openai/gpt-6-sol", "name": "GPT-6 Sol", "input": ["text", "image"], "contextWindow": 1050000},
    {"id": "openai/gpt-6-luna", "name": "GPT-6 Luna", "input": ["text", "image"], "contextWindow": 1050000,
     "cost": {"input": 0.10, "output": 0.50}},
    {"id": "anthropic/claude-opus-5-5", "name": "anthropic/claude-opus-5-5", "input": ["text"],
     "cost": {"input": 5, "output": 25}},
]}


def test_total_prices_each_session_by_its_own_model():
    prices = rc.prices(PROVIDER)
    # writers: (900k + 700k) in, 70k out at 5/25; one critic: 500k in, 20k out at 0.10/0.50
    expected = (1_600_000 * 5 + 70_000 * 25 + 500_000 * 0.10 + 20_000 * 0.50) / 1_000_000
    rows = [r for r in rc.sessions(FIX) if r.get("model") != "openai/gpt-6-sol"]
    assert rc.total(rows, prices) == pytest.approx(expected)


def test_unpriced_sessions_are_counted_not_guessed():
    rows = rc.sessions(FIX)
    assert rc.unpriced(rows, rc.prices(PROVIDER)) == 2  # the conductor and the coordinator, on Sol
    assert rc.total(rows, rc.prices(PROVIDER)) is None


def test_no_priced_session_is_unknown_not_zero():
    assert rc.total([{"key": "a", "modelProvider": "plow", "model": "openai/gpt-6-sol",
                      "inputTokens": 10, "outputTokens": 1}], rc.prices(PROVIDER)) is None
    assert rc.total([], rc.prices(PROVIDER)) is None


def test_a_truncated_listing_is_refused():
    with pytest.raises(ValueError, match="truncated"):
        rc.sessions({**FIX, "hasMore": True})
    with pytest.raises(ValueError):
        rc.sessions({"nope": []})


@pytest.mark.parametrize("spent, longest, ok", [(10, 20, True), (80, 20, True), (85, 20, False), (None, 20, False)])
def test_can_start_respects_the_ceiling(spent, longest, ok):
    assert rc.can_start(spent, longest, 100) is ok


def test_cli_total_reads_the_listing_and_the_provider_config(tmp_path, capsys, monkeypatch):
    provider = tmp_path / "plow-provider.json5"
    provider.write_text(json.dumps(PROVIDER))
    monkeypatch.setattr(rc, "PROVIDER_CONFIG", str(provider))
    calls = []

    def listing(argv):
        calls.append(argv)
        return json.dumps(FIX)

    assert rc.main(["total", "--since-minutes", "240"], run=listing) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["usd"] is None
    assert out["unpriced"] == 2
    assert calls == [["node", "/app/openclaw.mjs", "sessions", "--json", "--limit", "all", "--active", "240"]]


@pytest.mark.parametrize("argv, code", [
    (["--spent", "10", "--longest", "20", "--max", "100"], 0),
    (["--spent", "90", "--longest", "20", "--max", "100"], 1),
    (["--spent", "null", "--longest", "20", "--max", "100"], 1),
])
def test_cli_can_start_exits_on_the_ceiling(argv, code):
    assert rc.main(["can-start", *argv]) == code
