"""register_crons.py -- the spec derivation and the refusals with teeth."""
from __future__ import annotations

import json

import pytest

from conftest import ROOT, load_module

crons = load_module("pt_crons", "memo-schedule/scripts/register_crons.py")
backend_mod = load_module("cron_backend", "memo-schedule/scripts/cron_backend.py")

TZ = "America/Los_Angeles"
FUTURE = "2099-01-01T07:03:00-03:00"
CONFIG = {
    "owner": {"timezone": TZ},
    "delivery": {"hour": "07:00"},
    "printer": {"configured": False, "name": None},
    "memo": {"start": "01:00", "window_minutes": 240},
}


def write_config(tmp_path, config=CONFIG):
    path = tmp_path / "pt" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))
    return path


def row(name, enabled=True, jid=None, expr=None, tz=None, at=None, message=None, model=None, timeout=18000):
    """One automation as `openclaw cron list --json` returns it."""
    schedule = {}
    if at is not None:
        schedule = {"kind": "at", "at": at}
    elif expr is not None:
        schedule = {"kind": "cron", "expr": expr, **({"tz": tz} if tz else {})}
    payload = {"kind": "agentTurn"}
    if message is not None:
        payload["message"] = message
    if model is not None:
        payload["model"] = model
    if timeout is not None:  # None: a job registered before the budget was set
        payload["timeoutSeconds"] = timeout
    return {"id": jid or f"id-{name}", "name": name, "enabled": enabled,
            "sessionTarget": "isolated", "schedule": schedule, "payload": payload,
            "delivery": {"mode": "none"}}


class Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class FakeScheduler:
    """`node /app/openclaw.mjs cron ...` against an in-memory job list."""

    def __init__(self, rows=(), fail=None, listing=None):
        self.rows = list(rows)
        self.fail = fail or (lambda argv: 0)
        self.listing = listing
        self.calls = []

    def __call__(self, argv):
        assert argv[:3] == ["node", "/app/openclaw.mjs", "cron"], argv
        self.calls.append(argv)
        if argv[3] == "list":
            stdout = self.listing if self.listing is not None else json.dumps(
                {"jobs": self.rows, "total": len(self.rows), "hasMore": False})
            return Proc(0, stdout)
        rc = self.fail(argv)
        return Proc(rc, "", "boom" if rc else "")

    @property
    def writes(self):
        return [c[3:] for c in self.calls if c[3] != "list"]

    def backend(self):
        return backend_mod.CronBackend(self)


class TestNightlyJob:
    def test_registers_exactly_one_job_at_the_owner_local_hour(self, tmp_path, monkeypatch):
        sched = FakeScheduler()
        config = {**CONFIG, "owner": {"timezone": "America/Sao_Paulo"}}
        assert run_main(tmp_path, monkeypatch, sched, config=config) == 0
        adds = [w for w in sched.writes if w[0] == "add"]
        agent_jobs = [w for w in adds if "--message" in w]
        assert [w[w.index("--name") + 1] for w in agent_jobs] == ["memo-nightly"]
        (nightly,) = agent_jobs
        assert nightly[nightly.index("--cron") + 1] == "0 1 * * *"
        assert nightly[nightly.index("--tz") + 1] == "America/Sao_Paulo"
        assert nightly[nightly.index("--session") + 1] == "isolated"
        assert "--no-deliver" in nightly and "--exact" in nightly

    def test_defaults_are_one_am_and_four_hours(self, tmp_path):
        path = write_config(tmp_path, {k: v for k, v in CONFIG.items() if k != "memo"})
        assert crons.load_memo(path) == ("01:00", 240)

    def test_the_run_budget_covers_the_window_and_the_publish(self):
        job = crons.nightly_job("23:30", 240, TZ)
        assert job["schedule"] == "30 23 * * *"
        assert job["timeout"] == (240 + crons.PUBLISH_MARGIN_MINUTES) * 60
        argv = backend_mod.CronBackend().create_argv(job)
        assert argv[argv.index("--timeout-seconds") + 1] == str(job["timeout"])
        assert crons.stale_run_minutes(240) > job["timeout"] / 60

    @pytest.mark.parametrize("memo, why", [
        ({"start": "1am"}, "HH:MM"), ({"start": "24:00"}, "HH:MM"),
        ({"window_minutes": 0}, "positive integer"), ({"window_minutes": "240"}, "positive integer"),
        ("tonight", "must be an object"),
    ])
    def test_a_bad_memo_config_is_refused(self, tmp_path, memo, why):
        with pytest.raises(SystemExit, match=why):
            crons.load_memo(write_config(tmp_path, {**CONFIG, "memo": memo}))

    def test_deliver_job_is_a_command_with_no_agent(self, tmp_path, monkeypatch):
        sched = FakeScheduler()
        run_main(tmp_path, monkeypatch, sched)
        (add,) = [w for w in sched.writes if crons.DELIVER_NAME in w]
        assert add[add.index("--every") + 1] == "1m"
        assert json.loads(add[add.index("--command-argv") + 1]) == crons.DELIVER_ARGV
        for agent_only in ("--message", "--model", "--session"):
            assert agent_only not in add, agent_only


class TestPrompt:
    def test_the_prompt_hands_the_night_to_the_tournament_skill(self):
        prompt = crons.memo_prompt(180)
        assert prompt.startswith(crons.PAPER_RUN_MARKER)
        assert "/opt/plow/skills/memo-tournament/SKILL.md from its Start section" in prompt
        assert "The window is 180 minutes from when this run starts" in prompt
        assert "This run is scheduled." in prompt
        assert "This run is on demand." in crons.memo_prompt(180, scheduled=False)
        assert (ROOT / "memo-tournament" / "SKILL.md").is_file()

    def test_the_prompt_says_how_skills_load(self):
        # A model that guessed plow__plow_read_skill got "no skill" and gave up the run.
        prompt = crons.memo_prompt()
        assert "/opt/plow/skills/<name>/SKILL.md with the read tool" in prompt
        assert "plow__plow_read_skill reads the owner's Mac" in prompt

    def test_a_failure_before_delivery_sends_exactly_one_owner_notice(self):
        prompt = crons.memo_prompt()
        assert prompt.count("send exactly one short message to the owner") == 1
        assert "target plow-owner" in prompt and "memo was not delivered" in prompt
        assert "Do not send this notice after confirmed delivery" in prompt
        assert "NO_REPLY" not in prompt and "--deliver " not in prompt

    def test_no_prompt_asks_the_model_to_work_out_a_date(self):
        prompt = crons.memo_prompt()
        assert "<today" not in prompt and "<date>" not in prompt and "python3" not in prompt


class TestListing:
    def test_on_demand_job_keeps_its_run_for_diagnosis(self):
        backend = backend_mod.CronBackend()
        now = {"name": crons.NOW_NAME, "schedule": FUTURE, "tz": None,
               "prompt": crons.memo_prompt(), "keep_after_run": True}
        assert "--keep-after-run" in backend.create_argv(now)
        assert "--keep-after-run" not in backend.create_argv(crons.nightly_job("01:00", 240, TZ))

    def test_lists_disabled_jobs_too(self):
        sched = FakeScheduler([row("memo-nightly", enabled=False)])
        jobs = sched.backend().list()
        assert sched.calls == [["node", "/app/openclaw.mjs", "cron", "list", "--all", "--json"]]
        assert [(j.name, j.enabled) for j in jobs] == [("memo-nightly", False)]

    @pytest.mark.parametrize("listing", ["garbage", json.dumps({"nope": []}),
                                         json.dumps({"jobs": [{"name": "no id"}]}),
                                         json.dumps({"jobs": "x"})])
    def test_unreadable_listing_aborts(self, listing):
        with pytest.raises(SystemExit, match="refusing to register"):
            FakeScheduler(listing=listing).backend().list()

    def test_truncated_listing_aborts(self):
        listing = json.dumps({"jobs": [], "total": 250, "hasMore": True})
        with pytest.raises(SystemExit, match="truncated"):
            FakeScheduler(listing=listing).backend().list()

    def test_failed_listing_aborts(self):
        def runner(argv):
            return Proc(1, "", "gateway unreachable")
        with pytest.raises(SystemExit, match="could not list"):
            backend_mod.CronBackend(runner).list()

    def test_only_memo_jobs_are_managed(self):
        jobs = FakeScheduler([row("heartbeat-main"), row("memo-nightly"),
                              row("Memory Dreaming Promotion")]).backend().list()
        assert list(crons.registered_jobs(jobs)) == ["memo-nightly"]

    def test_a_managed_name_registered_twice_is_refused(self):
        jobs = FakeScheduler([row("memo-nightly", jid="a"), row("memo-nightly", jid="b")]).backend().list()
        with pytest.raises(SystemExit, match="registered twice"):
            crons.registered_jobs(jobs)

    def test_on_demand_copies_are_not_managed_by_name(self):
        jobs = FakeScheduler([row(crons.NOW_NAME, jid="a"), row(crons.NOW_NAME, jid="b")]).backend().list()
        assert crons.registered_jobs(jobs) == {}


class TestLoadOwnerZone:
    def test_names_the_owner_zone(self, tmp_path):
        assert crons.load_owner_zone(write_config(tmp_path)) == TZ

    def test_blank_owner_timezone_refuses(self, tmp_path):
        with pytest.raises(SystemExit, match="blank owner.timezone"):
            crons.load_owner_zone(write_config(tmp_path, {**CONFIG, "owner": {"timezone": " "}}))

    def test_missing_config_refuses(self, tmp_path):
        with pytest.raises(SystemExit, match="is missing"):
            crons.load_owner_zone(tmp_path / "nope.json")


def run_main(tmp_path, monkeypatch, sched, argv=None, config=CONFIG):
    pt_home = tmp_path / "pt"
    pt_home.mkdir(exist_ok=True)
    (pt_home / "config.json").write_text(json.dumps(config))
    monkeypatch.setenv("PT_HOME", str(pt_home))
    return crons.main(argv, backend=sched.backend(), config_path=pt_home / "config.json")


def registered_like_spec(**overrides):
    """Rows exactly as a previous run of this script would have left them."""
    job = crons.nightly_job("01:00", 240, TZ)
    return [row(job["name"], expr=job["schedule"], tz=job["tz"], message=job["prompt"],
                model="plow/openai/gpt-6-sol", timeout=job["timeout"], **overrides), deliver_row()]


def deliver_row(argv=None, enabled=True):
    """The memo-deliver job as `openclaw cron list --json` returns a command job."""
    return {"id": "id-memo-deliver", "name": "memo-deliver", "enabled": enabled, "sessionTarget": "isolated",
            "schedule": {"kind": "every", "everyMs": 60000},
            "payload": {"kind": "command", "argv": argv if argv is not None else crons.DELIVER_ARGV},
            "delivery": {"mode": "none"}}


class TestMain:
    def test_idempotent_run_skips_present(self, tmp_path, monkeypatch):
        sched = FakeScheduler(registered_like_spec())
        assert run_main(tmp_path, monkeypatch, sched) == 0
        assert sched.writes == []

    def test_foreign_jobs_are_never_touched(self, tmp_path, monkeypatch):
        sched = FakeScheduler(registered_like_spec() + [row("heartbeat-main", expr="*/30 * * * *"),
                                                         row("pt-daily-edition", expr="0 7 * * *")])
        run_main(tmp_path, monkeypatch, sched)
        assert sched.writes == []

    def test_a_memo_job_the_spec_no_longer_names_is_removed_by_id(self, tmp_path, monkeypatch):
        sched = FakeScheduler(registered_like_spec() + [row("memo-retired", jid="old")])
        run_main(tmp_path, monkeypatch, sched)
        assert sched.writes == [["rm", "old", "--json"]]

    @pytest.mark.parametrize("change, edited", [
        ({"memo": {"start": "02:30", "window_minutes": 240}}, "--cron"),
        ({"owner": {"timezone": "Europe/Lisbon"}}, "--tz"),
        ({"memo": {"start": "01:00", "window_minutes": 180}}, "--message"),
    ])
    def test_a_changed_config_edits_the_job_in_place(self, tmp_path, monkeypatch, change, edited):
        sched = FakeScheduler(registered_like_spec())
        run_main(tmp_path, monkeypatch, sched, config={**CONFIG, **change})
        (edit,) = sched.writes
        assert edit[:2] == ["edit", "id-memo-nightly"] and edited in edit

    def test_a_job_on_the_schedulers_default_budget_drifts(self, tmp_path, monkeypatch):
        rows = registered_like_spec()
        rows[0]["payload"]["timeoutSeconds"] = 10800
        sched = FakeScheduler(rows)
        run_main(tmp_path, monkeypatch, sched)
        (edit,) = sched.writes
        assert edit[edit.index("--timeout-seconds") + 1] == str(crons.run_timeout_seconds(240))

    def test_disabled_job_is_left_disabled_and_named(self, tmp_path, monkeypatch, capsys):
        sched = FakeScheduler(registered_like_spec(enabled=False))
        with pytest.raises(SystemExit, match="DISABLED"):
            run_main(tmp_path, monkeypatch, sched)
        assert sched.writes == []
        assert "cron enable id-memo-nightly" in capsys.readouterr().out

    def test_unreadable_listing_writes_nothing(self, tmp_path, monkeypatch):
        sched = FakeScheduler(listing="not json")
        with pytest.raises(SystemExit, match="refusing to register"):
            run_main(tmp_path, monkeypatch, sched)
        assert sched.writes == []

    def test_failed_create_fails_loud(self, tmp_path, monkeypatch):
        with pytest.raises(SystemExit, match="could not register"):
            run_main(tmp_path, monkeypatch, FakeScheduler(fail=lambda argv: 1))


class TestNow:
    def test_now_queues_the_nightly_prompt_as_a_one_shot(self, tmp_path, monkeypatch, capsys):
        sched = FakeScheduler(registered_like_spec())
        assert run_main(tmp_path, monkeypatch, sched, argv=["--now"]) == 0
        (create,) = [w for w in sched.writes if crons.NOW_NAME in w]
        at = create[create.index("--at") + 1]
        assert "T" in at and at[-6] in "+-"
        assert create[create.index("--message") + 1] == crons.memo_prompt(240, scheduled=False)
        assert "--keep-after-run" in create
        assert "queued: memo-now" in capsys.readouterr().out

    @pytest.mark.parametrize("create_rc", [0, 1])
    def test_the_previous_one_shot_goes_only_after_its_successor_is_queued(self, tmp_path, monkeypatch, create_rc):
        def fail(argv):
            return create_rc if argv[3] == "add" and crons.NOW_NAME in argv else 0
        sched = FakeScheduler(registered_like_spec() + [row(crons.NOW_NAME, jid="old123", at=FUTURE)], fail=fail)
        if create_rc:
            with pytest.raises(SystemExit, match="could not queue"):
                run_main(tmp_path, monkeypatch, sched, argv=["--now"])
            assert not any(w[0] == "rm" for w in sched.writes)
        else:
            run_main(tmp_path, monkeypatch, sched, argv=["--now"])
            assert [w[:2] for w in sched.writes] == [["add", "--name"], ["rm", "old123"]]

    @pytest.mark.parametrize("name", [crons.NOW_NAME, crons.NIGHTLY_NAME])
    def test_nothing_is_queued_behind_a_running_night(self, tmp_path, monkeypatch, capsys, name):
        listing = registered_like_spec()
        if name == crons.NOW_NAME:
            listing.append(row(name, jid="live123", at=FUTURE))
        (running,) = [r for r in listing if r["name"] == name]
        running["state"] = {"runningAtMs": 1790620326000}
        sched = FakeScheduler(listing)
        assert run_main(tmp_path, monkeypatch, sched, argv=["--now"]) == 0
        assert sched.writes == []
        assert f"already running: {name}" in capsys.readouterr().out


class TestCliPassesItsArguments:
    def test_module_entry_point_forwards_sys_argv(self):
        source = (ROOT / "memo-schedule" / "scripts" / "register_crons.py").read_text()
        assert "main(sys.argv[1:])" in source, "the CLI entry drops its arguments"


def test_jobs_follow_the_model_boot_exports(monkeypatch):
    # Boot exports the chat's model as PT_MODEL; a job still registered under Plow
    # after the install moved reads as drift, so the next register moves it.
    monkeypatch.setenv("PT_MODEL", "openai/gpt-6-sol")
    moved = load_module("cron_backend_moved", "memo-schedule/scripts/cron_backend.py")
    assert moved.MODEL == "openai/gpt-6-sol"
    monkeypatch.setattr(crons, "MODEL", moved.MODEL)
    job = crons.nightly_job("01:00", 240, TZ)
    on_plow = {"schedule": job["schedule"], "tz": TZ, "prompt": job["prompt"],
               "model": "plow/openai/gpt-6-sol", "command": None, "timeout": job["timeout"]}
    assert crons.job_drift(job, on_plow) is True
    assert crons.job_drift(job, {**on_plow, "model": "openai/gpt-6-sol"}) is False


def test_without_pt_model_jobs_stay_on_plow(monkeypatch):
    monkeypatch.delenv("PT_MODEL", raising=False)
    assert load_module("cron_backend_default", "memo-schedule/scripts/cron_backend.py").MODEL == "plow/openai/gpt-6-sol"
