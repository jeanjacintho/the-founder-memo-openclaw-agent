"""The pt-config gate's invariants: the single definition of a valid config."""
from __future__ import annotations

import json

import pytest

from conftest import load_module

gate_mod = load_module("pt_config_gate", "memo-shared/scripts/pt_config_gate.py")


def run_gate(config, tmp_path):
    path = tmp_path / "config.json"
    if isinstance(config, str):
        path.write_text(config)
    else:
        path.write_text(json.dumps(config))
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        # main takes sys.argv (argv[1] is the path), not bare args.
        code = gate_mod.main(["pt_config_gate.py", str(path)])
    return buf.getvalue().strip(), code


VALID = {
    "owner": {"timezone": "America/Los_Angeles"},
    "memo": {"start": "01:00", "window_minutes": 240, "max_usd": 100},
    "printer": {"configured": False, "name": None},
}


class TestPass:
    def test_valid_config_is_silent(self, tmp_path):
        out, code = run_gate(VALID, tmp_path)
        assert out == ""
        assert code == 0

    def test_printer_name_optional_when_unconfigured(self, tmp_path):
        out, _ = run_gate({**VALID, "printer": {"configured": False}}, tmp_path)
        assert out == ""

    def test_configured_printer_with_name_passes(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "printer": {"configured": True, "name": "HP_LaserJet"}},
            tmp_path,
        )
        assert out == ""

class TestNotValidJSON:
    def test_unreadable_file(self, tmp_path):
        out, _ = run_gate(str(tmp_path / "missing.json"), tmp_path)
        assert out == "not valid JSON"

    def test_garbage(self, tmp_path):
        out, _ = run_gate("garbage", tmp_path)
        assert out == "not valid JSON"

    def test_non_object_top_level(self, tmp_path):
        out, _ = run_gate([1, 2], tmp_path)
        assert out == "not valid JSON"

    def test_non_string_timezone_collapses(self, tmp_path):
        out, _ = run_gate({**VALID, "owner": {"timezone": 42}}, tmp_path)
        assert out == "not valid JSON"

    def test_nan_fail_closes(self, tmp_path):
        out, _ = run_gate(
            '{"owner": {"timezone": "UTC"}, "memo": {"start": "01:00", "window_minutes": 240, "max_usd": 100},'
            ' "printer": {"configured": NaN}}',
            tmp_path,
        )
        assert out == "not valid JSON"


class TestInvariants:
    def test_blank_timezone(self, tmp_path):
        out, _ = run_gate({**VALID, "owner": {"timezone": "   "}}, tmp_path)
        assert "owner.timezone is blank" in out

    def test_blank_string_timezone(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "owner": {"timezone": "\t"}}, tmp_path
        )
        assert "owner.timezone is blank" in out

    @pytest.mark.parametrize("start", ["1:00", "24:00", "0100", "01:60", 100, None])
    def test_malformed_start(self, tmp_path, start):
        out, _ = run_gate({**VALID, "memo": {**VALID["memo"], "start": start}}, tmp_path)
        assert 'memo.start is not "HH:MM"' in out

    @pytest.mark.parametrize("start", ["01:30", "23:45", "00:05"])
    def test_start_accepts_any_real_minute(self, tmp_path, start):
        out, _ = run_gate({**VALID, "memo": {**VALID["memo"], "start": start}}, tmp_path)
        assert out == ""

    @pytest.mark.parametrize("window", [0, -5, "240", 240.5, True, None])
    def test_malformed_window(self, tmp_path, window):
        out, _ = run_gate({**VALID, "memo": {**VALID["memo"], "window_minutes": window}}, tmp_path)
        assert "memo.window_minutes is not a positive integer" in out

    @pytest.mark.parametrize("ceiling", [0, -1, "100", True, None])
    def test_malformed_ceiling(self, tmp_path, ceiling):
        out, _ = run_gate({**VALID, "memo": {**VALID["memo"], "max_usd": ceiling}}, tmp_path)
        assert "memo.max_usd is not a positive number" in out

    def test_a_fractional_ceiling_passes(self, tmp_path):
        out, _ = run_gate({**VALID, "memo": {**VALID["memo"], "max_usd": 37.5}}, tmp_path)
        assert out == ""

    def test_string_false_is_not_a_boolean(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "printer": {"configured": "false", "name": None}}, tmp_path
        )
        assert "printer.configured is not a boolean" in out

    def test_configured_printer_needs_a_name(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "printer": {"configured": True, "name": "   "}}, tmp_path
        )
        assert "printer.name is blank while printer.configured is true" in out

    def test_null_name_collapses_to_not_valid_json(self, tmp_path):
        # A null name is a shape the checks cannot inspect (non-string where
        # a string is required) -- the same collapse as the ld gate.
        out, _ = run_gate(
            {**VALID, "printer": {"configured": True, "name": None}}, tmp_path
        )
        assert out == "not valid JSON"

    def test_language_absent_is_valid(self, tmp_path):
        out, _ = run_gate(VALID, tmp_path)
        assert out == ""

    def test_language_accepts_a_plain_name(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "owner": {"timezone": "UTC", "language": "Mandarin Chinese"}},
            tmp_path,
        )
        assert out == ""

    def test_language_blank_refused(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "owner": {"timezone": "UTC", "language": "   "}}, tmp_path
        )
        assert "owner.language is blank" in out

    def test_signals_absent_is_valid(self, tmp_path):
        # An install from before signal sources existed: every source off.
        out, _ = run_gate(VALID, tmp_path)
        assert out == ""

    def test_signals_switches_pass(self, tmp_path):
        signals = {"group_chat": True, "email": False, "imessage": True}
        out, _ = run_gate({**VALID, "signals": signals}, tmp_path)
        assert out == ""

    def test_signals_switch_must_be_boolean(self, tmp_path):
        out, _ = run_gate({**VALID, "signals": {"group_chat": True, "email": "on", "imessage": False}}, tmp_path)
        assert "signals.email is not a boolean" in out

    def test_signals_unknown_source_is_refused(self, tmp_path):
        out, _ = run_gate({**VALID, "signals": {"group_chat": True, "sms": True}}, tmp_path)
        assert "signals.sms is not a signal source" in out

    def test_signals_must_be_an_object(self, tmp_path):
        out, _ = run_gate({**VALID, "signals": ["email"]}, tmp_path)
        assert "signals is not an object" in out

    def test_priority_absent_is_valid(self, tmp_path):
        config = dict(VALID)
        config.pop("priority", None)
        out, _ = run_gate(config, tmp_path)
        assert out == ""

    def test_priority_configured_must_be_boolean(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "priority": {"configured": "true", "file": "~/Plow/prioritization.md"}},
            tmp_path,
        )
        assert out == "priority.configured is not a boolean"

    def test_a_configured_desk_needs_no_path(self, tmp_path):
        out, _ = run_gate({**VALID, "priority": {"configured": True}}, tmp_path)
        assert out == ""

    def test_placeholder_anywhere(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "owner": {"timezone": "[OWNER_TZ]"}}, tmp_path
        )
        assert "an unfilled [UPPER_SNAKE] placeholder remains" in out

    def test_failures_join_with_semicolons(self, tmp_path):
        out, _ = run_gate(
            {"owner": {"timezone": "UTC"}, "memo": {"start": "nope", "window_minutes": 240, "max_usd": 100},
             "printer": {"configured": "no"}}, tmp_path
        )
        assert out == ('memo.start is not "HH:MM"; '
                       "printer.configured is not a boolean")


class TestExample:
    def test_filled_example_passes(self, tmp_path):
        import pathlib
        from conftest import ROOT

        example = (ROOT / "memo-shared/references/config.example.json").read_text()
        filled = (
            example.replace("[OWNER_TZ]", "America/Los_Angeles")
            .replace("[START_HOUR]", "01:00")
        )
        out, _ = run_gate(json.loads(filled), tmp_path)
        assert out == ""

    def test_the_example_itself_carries_placeholders(self, tmp_path):
        import json
        import pathlib
        from conftest import ROOT

        example = json.loads(
            (ROOT / "memo-shared/references/config.example.json").read_text()
        )
        out, _ = run_gate(example, tmp_path)
        assert "placeholder" in out
