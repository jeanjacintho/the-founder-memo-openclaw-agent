"""Immediate memo PDF delivery and duplicate-safe finalizer recovery."""
from __future__ import annotations

import json
from pathlib import Path
import types
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from conftest import ROOT, load_module

sys.path.insert(0, str(ROOT / "memo-shared" / "scripts"))
post = load_module("post_to_chat", "memo-shared/scripts/post_to_chat.py")

MORNING = datetime(2026, 9, 19, 6, 4, tzinfo=ZoneInfo("America/Sao_Paulo"))
AFTERNOON = datetime(2026, 9, 19, 14, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))



def owner_zone(monkeypatch, tmp_path, tz):
    """Delivery timestamps use the owner's timezone."""
    home = tmp_path / "pt-home"
    home.mkdir(exist_ok=True)
    (home / "config.json").write_text(json.dumps({"owner": {"timezone": tz}}))
    monkeypatch.setenv("PT_HOME", str(home))





def _exits(code, stderr="", stdout=""):
    return lambda *a, **k: types.SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


def _hangs(*a, **k):
    raise subprocess.TimeoutExpired(cmd="print_edition.py", timeout=k["timeout"])


class TestMissedPrintIsReported:
    """Measured 2026-09-22: a configured printer, a rendered PDF, no page and
    no word to the owner. Every miss now posts one line after the edition."""

    def _main(self, tmp_path, monkeypatch, argv, run=None, configured=True, language="English"):
        (tmp_path / "edition.json").write_text('{"date": "2026-09-22"}', encoding="utf-8")
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"owner": {"language": language},
                                   "printer": {"configured": configured, "name": "JV"}}),
                       encoding="utf-8")
        monkeypatch.setattr(post, "CONFIG_DEFAULT", str(cfg))
        monkeypatch.setenv("PLOW_MCP_URL", "https://relay.invalid/mcp")
        monkeypatch.setenv("PLOW_AGENT_TOKEN", "tok")
        monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
        monkeypatch.setattr(post, "resolve_chat", lambda: ("https://api.example", "cht_1", "tok"))
        monkeypatch.setattr(post, "declare_and_upload", lambda *a, **k: "att_1")
        monkeypatch.setattr(post, "run_record_memo", lambda *a: "RECORDED")
        if run:
            monkeypatch.setattr(subprocess, "run", run)
        bodies = []
        monkeypatch.setattr(post, "post_json", lambda *a: bodies.append(a[-1]["body"]))
        monkeypatch.setattr(sys, "argv", ["post_to_chat.py", *[
            str(tmp_path / x) if x.startswith("edition") else x for x in argv]])
        post.main()
        return bodies[1:]

    @pytest.mark.parametrize("run, notice", [
        (_exits(0, stdout="page printed on JV"), []),
        (_exits(0, stdout="skipped: printer.configured is not true"), []),
        (_exits(1, "error: lp 1: no such printer"),
         ["page not printed — lp 1: no such printer; next scheduled run retries"]),
        (_exits(1, "warning: first\nerror: Mac unreachable"),
         ["page not printed — Mac unreachable; next scheduled run retries"]),
        (_exits(1, "error: lp outcome unknown: still running"),
         ["page not printed — lp outcome unknown: still running"]),
        (_exits(1), ["page not printed — exit 1; next scheduled run retries"]),
        (_hangs, [f"page not printed — outcome unknown: still running after {post.PRINT_TIMEOUT}s"]),
    ])
    def test_pdf_leg_posts_one_line_only_for_a_missed_page(self, tmp_path, monkeypatch, run, notice):
        (tmp_path / "edition.pdf").write_bytes(b"%PDF")
        assert self._main(tmp_path, monkeypatch, ["--pdf", "edition.pdf"], run) == notice



class TestRunRecord:
    """post_to_chat.py records the edition itself now, the same way it prints."""

    def test_a_hung_recorder_times_out_instead_of_blocking_the_run(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="record_memo.py", timeout=kwargs.get("timeout"))

        monkeypatch.setattr(subprocess, "run", fake_run)
        out = post.run_record_memo("run/1/edition.json", MORNING)
        assert out == f"memo not recorded — timed out after {post.RECORD_TIMEOUT}s"

    def test_passes_the_delivered_at_it_was_given_as_the_now_flag(self, monkeypatch):
        # issue #48: this must be the timestamp captured right before the
        # chat POST, not a fresh clock read taken here after other
        # finalizers run.
        argv = []
        monkeypatch.setattr(subprocess, "run", lambda a, **k: argv.extend(a) or
                             types.SimpleNamespace(returncode=0, stdout="RECORDED x.md", stderr=""))
        post.run_record_memo("run/1/edition.json", MORNING)
        assert argv[-2:] == ["--now", MORNING.isoformat()]


class TestFinalizersRunIndependently:
    """The paper comes before the archive, and no finalizer's failure blocks
    another's: print and record each run best-effort, in order."""

    def _mock_main(self, tmp_path, monkeypatch, pdf_arg=None, **overrides):
        pdf = tmp_path / "edition.pdf"
        pdf.write_bytes(b"%PDF")
        monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
        monkeypatch.setattr(post, "resolve_chat", lambda: ("https://api.example", "cht_1", "tok"))
        monkeypatch.setattr(post, "declare_and_upload", lambda *a, **k: "att_1")
        monkeypatch.setattr(post, "post_json", lambda *a, **k: None)
        if "print_page" in overrides:
            monkeypatch.setattr(post, "print_page", overrides["print_page"])
        if "run_record_memo" in overrides:
            monkeypatch.setattr(post, "run_record_memo", overrides["run_record_memo"])
        monkeypatch.setattr(sys, "argv", ["post_to_chat.py", "--pdf", pdf_arg or str(pdf)])

    @pytest.mark.parametrize("print_result, recorded, error", [
        (None, "RECORDED", None),
        ("page not printed — lp 1", "RECORDED", None),
        (None, "error: memo not recorded — broken",
         r"record_memo.py <edition.json> --now \S+.*do not repost"),
        ("page not printed — lp 1", "error: memo not recorded — broken",
         r"record_memo.py <edition.json> --now \S+.*do not repost"),
    ])
    def test_finalizers_continue_in_order(self, tmp_path, monkeypatch,
                                          print_result, recorded, error):
        order = []
        paths = []
        self._mock_main(
            tmp_path, monkeypatch,
            print_page=lambda *a, **k: order.append("print") or print_result,
            run_record_memo=lambda path, delivered_at: paths.append(path) or order.append("record") or recorded,
        )
        if error:
            with pytest.raises(SystemExit, match=error):
                post.main()
        else:
            post.main()
        assert order == ["print", "record"]
        assert paths == [str(tmp_path / "edition.json")]
        # "print it again" (#92) gets the posted memo even when a finalizer failed.
        assert (tmp_path / "pt" / "last-edition" / "edition.pdf").read_bytes() == b"%PDF"

    def test_a_print_failure_before_its_own_runner_still_records(self, tmp_path, monkeypatch):
        # print_page is real here: a pdf path subprocess cannot pass must
        # still cost only the page, never the record.
        order = []
        self._mock_main(
            tmp_path, monkeypatch, pdf_arg="bad\x00path",
            run_record_memo=lambda *a, **k: order.append("record") or "RECORDED",
        )
        post.main()
        assert order == ["record"]

    def test_record_gets_the_post_moment_not_a_clock_read_after_the_slow_print_step(
            self, tmp_path, monkeypatch):
        # issue #48: the print step can poll for minutes; record_memo.py's
        # own now must not be sampled after it, or a fast-printing edition
        # could out-race an already-recorded one that posted first but
        # printed slower.
        clock = iter([MORNING, AFTERNOON])  # captured at POST, then print "later"
        monkeypatch.setattr(post, "owner_now", lambda: next(clock))
        seen = []

        def fake_print_page(*a, **k):
            post.owner_now()  # simulates the slow print step's own clock read
            return "page printed"

        self._mock_main(
            tmp_path, monkeypatch,
            print_page=fake_print_page,
            run_record_memo=lambda path, at: seen.append(at) or "RECORDED",
        )
        post.main()
        assert seen == [MORNING]

    def test_delivery_has_no_duplicate_path_adapters(self):
        assert not hasattr(post, "maybe_finalize_topics")
        assert not hasattr(post, "maybe_record")

    def test_a_bad_owner_timezone_fails_before_the_message_is_sent(self, tmp_path, monkeypatch):
        # srosro-review on 3eb4305: owner_now() can raise on a
        # configured-but-invalid owner.timezone. Raising AFTER post_json()
        # already delivered the message would skip every finalizer and
        # recovery command while the edition was still sent -- a retry
        # could then duplicate it. The clock read has to happen first.
        sent = []
        self._mock_main(tmp_path, monkeypatch)
        monkeypatch.setattr(post, "post_json", lambda *a, **k: sent.append(1))

        def bad_clock():
            raise KeyError("bad-zone")

        monkeypatch.setattr(post, "owner_now", bad_clock)
        with pytest.raises(KeyError):
            post.main()
        assert sent == []




class TestPrintMissInTheOwnersLanguage:
    """owner.language is free-form: a language with no curated lines speaks
    through the phrases the paper wrote for it, and English until it has."""

    ZH = {"print.lede": "页面未打印 — ", "print.retry": "；下一次定时运行会重试",
          "print.timeout": "结果未知：{seconds}秒后仍在运行", "print.no_pdf": "{path} 没有可打印的 PDF"}

    def _write_phrases(self, tmp_path, language):
        phrases = load_module("owner_phrases", "memo-shared/scripts/owner_phrases.py")
        table = {**{k: "ZH " + v for k, v in phrases.SOURCE.items()}, **self.ZH}
        home = tmp_path / "pt"
        home.mkdir(exist_ok=True)
        (home / "owner-phrases.json").write_text(json.dumps({"language": language, "phrases": table}, ensure_ascii=False))

    def _miss(self, tmp_path, monkeypatch):
        (tmp_path / "edition.pdf").write_bytes(b"%PDF")
        return TestMissedPrintIsReported()._main(tmp_path, monkeypatch, ["--pdf", "edition.pdf"],
                                                 _exits(1, "error: lp 1: no such printer"), language="Mandarin Chinese")

    def test_a_written_language_gets_its_own_line(self, tmp_path, monkeypatch):
        self._write_phrases(tmp_path, "Mandarin Chinese")
        assert self._miss(tmp_path, monkeypatch) == ["页面未打印 — lp 1: no such printer；下一次定时运行会重试"]

    def test_phrases_for_another_language_are_never_used(self, tmp_path, monkeypatch):
        self._write_phrases(tmp_path, "Deutsch")
        assert self._miss(tmp_path, monkeypatch) == ["page not printed — lp 1: no such printer; next scheduled run retries"]




class TestAttachmentFilenames:
    def test_attachment_filename_defaults_to_basename(self):
        assert post.attachment_filename("/var/lib/plow/pt/run/edition.pdf") == (
            "edition.pdf"
        )


    def test_attachment_filename_override_is_a_paper_name_not_a_path(self):
        # Measured live: the chat showed the attachment as "edition.pdf"
        # because declare used the run-dir basename. The owner asked for
        # the newspaper, not a working-file name.
        assert (
            post.attachment_filename(
                "/var/lib/plow/pt/run/edition.pdf",
                "The-Founder-Times-2026-09-17.pdf",
            )
            == "The-Founder-Times-2026-09-17.pdf"
        )
        with pytest.raises(SystemExit, match="filename"):
            post.attachment_filename("edition.pdf", "../secret.pdf")


class TestPostedDeliveryRecovery:
    def test_flush_recovers_persisted_post_without_reposting(self, tmp_path, monkeypatch):
        home = tmp_path / "pt"
        recovery = home / "delivery-recovery" / "posted-1"
        recovery.mkdir(parents=True)
        (home / "config.json").write_text(json.dumps({"owner": {"timezone": "America/Sao_Paulo"}}))
        (recovery / "edition.json").write_text(json.dumps({"date": "2026-09-25", "sections": []}))
        (recovery / "edition.pdf").write_bytes(b"%PDF posted edition")
        (recovery / "delivery.json").write_text(json.dumps({
            "delivered_at": MORNING.isoformat(),
            "edition_json": "edition.json",
            "pdf": "edition.pdf",
            "print_path": "edition.pdf",
            "finalizers_pending": ["print", "record"],
        }))
        monkeypatch.setenv("PT_HOME", str(home))
        order, posts = [], []
        monkeypatch.setattr(post, "print_page", lambda path: order.append(("print", Path(path).name)) or None)
        monkeypatch.setattr(post, "run_record_memo", lambda path, at: order.append(("record", Path(path).name)) or "RECORDED")
        monkeypatch.setattr(post, "post_json", lambda *args, **kwargs: posts.append(args))

        assert post.main_recover() == 0
        assert order == [("print", "edition.pdf"), ("record", "edition.json")]
        assert posts == [], "recovery must not repost the already delivered edition"
        assert not recovery.exists(), "completed recovery state is removed"
        assert not (home / "last-edition").exists(), "a late recovery must not replace the last posted memo"


    def test_ticket_removed_while_waiting_for_lock_is_already_complete(self, tmp_path, monkeypatch):
        recovery = tmp_path / "delivery-recovery" / "posted-1"
        recovery.mkdir(parents=True)
        ticket = recovery / "delivery.json"
        ticket.write_text("{}")
        real_flock = post.fcntl.flock

        def remove_before_lock(fd, operation):
            ticket.unlink(missing_ok=True)
            return real_flock(fd, operation)

        monkeypatch.setattr(post.fcntl, "flock", remove_before_lock)
        assert post.recover_delivery(ticket) == []


    def test_flush_skips_a_ticket_locked_by_another_process(self, tmp_path):
        import fcntl
        recovery = tmp_path / "delivery-recovery" / "posted-1"
        recovery.mkdir(parents=True)
        ticket = recovery / "delivery.json"
        ticket.write_text("{}")
        with open(recovery / ".recovery.lock", "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert post.recover_delivery(ticket, wait=False) == []


    def test_flush_ignores_hidden_building_recovery_ticket(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "pt"
        building = home / "delivery-recovery" / ".building-posted-1-123"
        building.mkdir(parents=True)
        ticket = building / "delivery.json"
        content = '{"finalizers_pending": ["print"]}\n'
        ticket.write_text(content)
        monkeypatch.setenv("PT_HOME", str(home))

        assert post.main_recover() == 0
        assert ticket.exists()
        assert ticket.read_text() == content
        assert "pending finalizers" not in capsys.readouterr().err


    def test_flush_isolates_malformed_recovery_ticket(self, tmp_path, monkeypatch):
        home = tmp_path / "pt"
        recovery = home / "delivery-recovery" / "broken"
        recovery.mkdir(parents=True)
        (recovery / "delivery.json").write_text(json.dumps({
            "edition_json": "edition.json", "delivered_at": "not-a-timestamp",
            "finalizers_pending": ["print"],
        }))
        monkeypatch.setenv("PT_HOME", str(home))
        assert post.main_recover() == 1


    def test_finalizer_stops_retrying_after_five_failures(self, tmp_path, monkeypatch):
        recovery = tmp_path / "delivery-recovery" / "posted-1"
        recovery.mkdir(parents=True)
        (recovery / "edition.json").write_text("{}")
        ticket = recovery / "delivery.json"
        ticket.write_text(json.dumps({
            "delivered_at": MORNING.isoformat(), "edition_json": "edition.json",
            "finalizers_pending": ["record"], "attempts": {},
        }))
        calls = []
        monkeypatch.setattr(post, "run_record_memo", lambda *args: calls.append(args) or "memo not recorded — broken")
        for _ in range(post.MAX_FINALIZER_ATTEMPTS):
            assert post.recover_delivery(ticket) == ["record"]
        assert post.recover_delivery(ticket) == ["record retry limit reached"]
        assert len(calls) == post.MAX_FINALIZER_ATTEMPTS


    def test_post_is_confirmed_before_recovery_persistence_and_failure_runs_inline(
            self, tmp_path, monkeypatch, capsys):
        run = tmp_path / "run"
        run.mkdir()
        pdf = run / "edition.pdf"
        pdf.write_bytes(b"%PDF")
        (run / "edition.json").write_text("{}")
        monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
        order = []
        monkeypatch.setattr(post, "owner_now", lambda: MORNING)
        monkeypatch.setattr(post, "declare_and_upload", lambda *a, **k: "att_1")
        monkeypatch.setattr(post, "post_json", lambda *a: order.append("post"))
        monkeypatch.setattr(post, "persist_posted_delivery",
                            lambda *a: order.append("persist") or (_ for _ in ()).throw(OSError("disk full")))
        monkeypatch.setattr(post, "print_page", lambda *a: order.append("print") or None)
        monkeypatch.setattr(post, "run_record_memo", lambda *a: order.append("record") or "RECORDED")
        post.deliver("https://api.example", "chat", "token", pdf=str(pdf),
                     on_posted=lambda: order.append("clear attempts"))
        assert order == ["post", "clear attempts", "persist", "print", "record"]
        assert "running finalizers inline" in capsys.readouterr().err


class TestConfirmedPostAttempts:
    @pytest.mark.parametrize("clear", [True, False])
    def test_only_a_confirmed_post_clears_attempts_when_requested(self, tmp_path, monkeypatch, capsys, clear):
        home = tmp_path / "pt"
        home.mkdir()
        monkeypatch.setenv("PT_HOME", str(home))
        pdf = tmp_path / "edition.pdf"
        pdf.write_bytes(b"%PDF")
        monkeypatch.setattr(post, "resolve_chat", lambda: ("https://api.example", "chat", "token"))
        monkeypatch.setattr(post, "declare_and_upload", lambda *a, **k: "att_1")
        posts = []
        monkeypatch.setattr(post, "post_json", lambda *a: posts.append(a[-1]))
        monkeypatch.setattr(post, "print_page", lambda *a: None)
        monkeypatch.setattr(post, "run_record_memo", lambda *a: "RECORDED")
        for _ in range(post.run_attempts.MAX_ATTEMPTS):
            post.run_attempts.begin()
        capsys.readouterr()
        monkeypatch.setattr(sys, "argv", ["post_to_chat.py", "--pdf", str(pdf), *(["--clear-attempts"] if clear else [])])
        post.main()
        assert posts == [{"body": "", "attachment_uids": ["att_1"]}]
        capsys.readouterr()
        post.run_attempts.begin()
        assert (capsys.readouterr().out.strip() == "proceed") is clear

    def test_failed_post_never_clears_attempts_or_starts_finalizers(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
        monkeypatch.setattr(post, "owner_now", lambda: MORNING)
        monkeypatch.setattr(post, "declare_and_upload", lambda *a, **k: "att_1")
        def fail(*a):
            raise SystemExit("HTTP 503")
        monkeypatch.setattr(post, "post_json", fail)
        called = []
        monkeypatch.setattr(post, "persist_posted_delivery", lambda *a: called.append("persist"))
        with pytest.raises(SystemExit, match="HTTP 503"):
            post.deliver("https://api.example", "chat", "token", pdf="edition.pdf", on_posted=lambda: called.append("clear"))
        assert called == []
