#!/usr/bin/env python3
"""Register the memo's crons, idempotently, from pt/config.json.

Why this exists at all. The scheduler keeps its jobs in the gateway's state
volume; a fresh volume has none, and nothing else replays them. Keeping the
spec here, derived from pt/config.json, means "set up the crons" replays a
reviewed derivation instead of improvising schedules from a sentence.

The spec:

  memo-nightly   <min> <hour> * * *, memo.start   the night's run; its budget
                 (default 01:00) in owner.timezone is memo.window_minutes
                                                   (default 240) plus the
                                                   publish margin
  memo-deliver   every minute                      no-agent command job:
                                                   resumes post-delivery
                                                   finalizers that failed
  memo-now       one-shot, a minute out            --now: tonight's run on
                                                   demand, same prompt
  memo-bootstrap one-shot, a minute out            once, right after setup
                                                   (finalize_setup.py): the
                                                   first full-history read

The cron job carries `--tz owner.timezone`: memo.start is the owner's wall
clock, and the scheduler fires on it directly, daylight saving included. The
window counts from when the run actually starts, not from the nominal hour.
Each job is an agent turn in an isolated session with delivery `none`; the
memo reaches chat through post_to_chat.py.

This script CREATES missing jobs, RECONCILES drift (schedule, zone, prompt,
model or run budget) in place with `cron edit`, and REMOVES a registered
memo-* job the spec no longer names. It never touches a job whose name does
not start with memo-: OpenClaw keeps its own jobs in the same list. Never
remove-then-create a drifted job: if create failed after remove, the night
had no job until someone reran the script.

One refusal is the point of the script: an unreadable, partial or
unexpected job listing aborts. Never read "I could not tell what is
registered" as "nothing is" -- that re-registers every job and duplicates
all of them.

It runs INSIDE the container, from a turn: exec inherits the gateway token
the scheduler CLI needs.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_SKILLS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_SKILLS, "memo-shared", "scripts"))
from pt_paths import config_file, pt_home, skills  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from cron_backend import MODEL, OPENCLAW, PAPER_TIMEOUT_SECONDS, CronBackend  # noqa: E402 -- sibling module

CONFIG_FILE = str(config_file())
NIGHTLY_NAME = "memo-nightly"
# The on-demand run (--now): a one-shot the sweep never removes, so a queued
# run survives a registration; the next --now replaces it unless it is running.
NOW_NAME = "memo-now"
# The first read of the owner's company, once, right after setup: never swept,
# never re-queued (pt/bootstrap.json records that it was).
BOOTSTRAP_NAME = "memo-bootstrap"
# Resumes post_to_chat.py's recovery tickets: a memo posted whose print or
# record failed is finished the next minute without posting it again. No
# model, no tokens; drifts only on its command. The venv's python: a command
# job's PATH is the gateway's.
DELIVER_NAME = "memo-deliver"
DELIVER_ARGV = ["/opt/plow/pt-venv/bin/python3",
                "/opt/plow/skills/memo-shared/scripts/post_to_chat.py", "--flush-outbox"]
DEFAULT_START = "01:00"
DEFAULT_WINDOW_MINUTES = 240
# Render, print, post and record after the window closes.
PUBLISH_MARGIN_MINUTES = 60
WORKSPACE_LOCK = "paper-workspace"
_START_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

DELIVERY_FAILURE_NOTICE = (
    "This is a memo run, not a heartbeat: run the whole night. "
    "Do not finish the run before post_to_chat.py confirms the chat post. "
    "After that confirmation, finish with a short status for the cron run record; "
    "the cron reply is not delivered to chat. "
    "If any step stops, refuses or fails before post_to_chat.py confirms delivery, "
    "release the paper-workspace lock if you hold it, then send exactly one short "
    "message to the owner with message(action=send), channel plow, accountId chat, "
    "target plow-owner. Say the memo was not delivered and give the reason in "
    "one sentence. Do not send this notice after confirmed delivery."
)
PAPER_RUN_MARKER = "[PLOW_PAPER_RUN]"
# Measured live: gpt-6-luna asked plow__plow_read_skill (the owner's Mac)
# for a research skill, got "no skill named", and gave up the paper. The memo-*
# skills live in this container and only the read tool reaches them.
SKILL_LOADING = (
    "Load each memo-* skill by reading /opt/plow/skills/<name>/SKILL.md with the read "
    "tool (its references and scripts sit beside it); plow__plow_read_skill reads the "
    "owner's Mac, which does not have them. "
)


def run_timeout_seconds(window_minutes):
    return (window_minutes + PUBLISH_MARGIN_MINUTES) * 60


def stale_run_minutes(window_minutes):
    """A lock older than the run's own budget belongs to a run that is gone."""
    return run_timeout_seconds(window_minutes) // 60 + 20


def memo_prompt(window_minutes=DEFAULT_WINDOW_MINUTES, scheduled=True):
    """The one run prompt, nightly or on demand. Everything else -- the lock, the
    day's attempts, the Mac gate, the phases -- is memo-tournament's Start."""
    return (
        f"{PAPER_RUN_MARKER} {SKILL_LOADING}"
        f"Run tonight's memo now, in one session: follow "
        f"{skills() / 'memo-tournament' / 'SKILL.md'} from its Start section. "
        f"This run is {'scheduled' if scheduled else 'on demand'}. "
        f"The window is {window_minutes} minutes from when this run starts "
        f"(stale lock after {stale_run_minutes(window_minutes)} minutes). "
        f"{DELIVERY_FAILURE_NOTICE}"
    )


def bootstrap_prompt(window_minutes=DEFAULT_WINDOW_MINUTES):
    return (
        f"{SKILL_LOADING}"
        f"Run the memo's bootstrap now, in one session: follow "
        f"{skills() / 'memo-tournament' / 'SKILL.md'} § Bootstrap. "
        f"The window is {window_minutes} minutes from when this run starts "
        f"(stale lock after {stale_run_minutes(window_minutes)} minutes). "
        "If it stops before its summary is posted, release the paper-workspace lock if you hold "
        "it, then send exactly one short message to the owner with message(action=send), channel "
        "plow, accountId chat, target plow-owner, saying the first read of their company did not "
        "finish and tonight's run will read it instead."
    )


def queue_bootstrap(backend, owner_tz, window_minutes=DEFAULT_WINDOW_MINUTES, clock=None, home=None):
    """memo-bootstrap a minute out, once per install. Prints what it did."""
    marker = (home or pt_home()) / "bootstrap.json"
    if marker.exists() or any(j.name == BOOTSTRAP_NAME for j in backend.list()):
        print(f"already queued: {BOOTSTRAP_NAME}")
        return
    at = (clock or datetime.now(ZoneInfo(owner_tz))) + timedelta(minutes=1)
    job = {"name": BOOTSTRAP_NAME, "schedule": at.isoformat(timespec="seconds"), "tz": None,
           "prompt": bootstrap_prompt(window_minutes), "timeout": run_timeout_seconds(window_minutes),
           "keep_after_run": True}
    _check(backend.create(job), f"could not queue {BOOTSTRAP_NAME}")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"queued_for": job["schedule"]}) + "\n")
    print(f"queued: {BOOTSTRAP_NAME} ({job['schedule']})")


def _config(config_path):
    path = pathlib.Path(config_path)
    try:
        return path, json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f"refusing to register: {path} is missing -- memo-setup writes it.") from None
    except (OSError, ValueError) as exc:
        raise SystemExit(f"refusing to register: malformed {path} ({exc!r}).") from exc


def load_owner_zone(config_path=CONFIG_FILE):
    """owner.timezone, or refuse: every schedule here is written against it."""
    path, config = _config(config_path)
    try:
        owner = config["owner"]["timezone"]
    except (KeyError, TypeError) as exc:
        raise SystemExit(f"refusing to register: could not read owner.timezone from {path} ({exc!r}).") from exc
    if not str(owner or "").strip():
        raise SystemExit(f"refusing to register: {path} has a blank owner.timezone.")
    return owner


def load_memo(config_path=CONFIG_FILE):
    """(memo.start, memo.window_minutes) with their defaults, or refuse a bad value."""
    path, config = _config(config_path)
    memo = config.get("memo") or {}
    if not isinstance(memo, dict):
        raise SystemExit(f"refusing to register: {path} has memo={memo!r}; it must be an object.")
    start = memo.get("start", DEFAULT_START)
    window = memo.get("window_minutes", DEFAULT_WINDOW_MINUTES)
    if not isinstance(start, str) or not _START_RE.fullmatch(start):
        raise SystemExit(f'refusing to register: {path} has memo.start={start!r}; it must be "HH:MM".')
    if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
        raise SystemExit(f"refusing to register: {path} has memo.window_minutes={window!r}; "
                         "it must be a positive integer.")
    return start, window


def nightly_job(start, window_minutes, owner_tz):
    hour, minute = (int(part) for part in start.split(":"))
    return {"name": NIGHTLY_NAME, "schedule": f"{minute} {hour} * * *", "tz": owner_tz,
            "prompt": memo_prompt(window_minutes), "timeout": run_timeout_seconds(window_minutes)}


def deliver_job():
    return {"name": DELIVER_NAME, "every": "1m", "schedule": None, "tz": None,
            "prompt": None, "command": DELIVER_ARGV}


def desired_jobs(start, window_minutes, owner_tz):
    return [nightly_job(start, window_minutes, owner_tz), deliver_job()]


def registered_jobs(listing):
    """{name: job} for the memo-* jobs this spec manages, from a full listing.

    A managed name registered twice is refused rather than guessed at --
    editing or sweeping one of two copies leaves the other firing. The
    on-demand run is the exception: queue_now replaces it by id.
    """
    registered = {}
    for job in listing:
        if not job.name.startswith("memo-") or job.name in (NOW_NAME, BOOTSTRAP_NAME):
            continue
        if job.name in registered:
            raise SystemExit(
                f"refusing to register: {job.name} is registered twice "
                f"({registered[job.name].id}, {job.id}). Remove one with "
                f"`{' '.join(OPENCLAW)} cron rm <id>` and re-run.")
        registered[job.name] = job
    return registered


def job_drift(job, spec):
    """True when a registered job's reported fields contradict the spec.

    Only a field that is BOTH reported and different is a drift; an absent
    field is silence, not a mismatch. The run budget is the exception: a job
    that reports a timeout field with no value runs on the scheduler's
    60-minute default, which ends the night mid-run.
    """
    if job.get("command") is not None:  # a command job has no prompt or model
        return spec.get("command") is not None and spec["command"] != job["command"]
    if "timeout" in spec and spec["timeout"] != job.get("timeout", PAPER_TIMEOUT_SECONDS):
        return True
    for key in ("schedule", "tz", "prompt", "model"):
        have = spec.get(key)
        want = job.get(key, MODEL) if key == "model" else job.get(key)
        if have is not None and want is not None and have != want:
            return True
    return False


def queue_now(backend, listing, window_minutes, owner_tz, clock=None):
    """Tonight's run on demand: the nightly prompt as a one-shot a minute out.

    Previous copies are removed by id only after the new one is created, so a
    failed create never cancels a run the owner was already promised. While a
    run is in flight nothing is queued: `cron rm` aborts its session mid-run,
    and a copy queued behind it reads 'held' and stops.
    """
    running = [j for j in listing if j.name in (NIGHTLY_NAME, NOW_NAME) and j.running]
    if running:
        print(f"already running: {running[0].name} ({running[0].id}) -- its memo is on the way")
        return
    at = (clock or datetime.now(ZoneInfo(owner_tz))) + timedelta(minutes=1)
    job = {"name": NOW_NAME, "schedule": at.isoformat(timespec="seconds"), "tz": None,
           "prompt": memo_prompt(window_minutes, scheduled=False),
           "timeout": run_timeout_seconds(window_minutes), "keep_after_run": True}
    previous = [j.id for j in listing if j.name == NOW_NAME]
    _check(backend.create(job), f"could not queue {NOW_NAME}")
    print(f"queued: {NOW_NAME} ({job['schedule']})")
    for job_id in previous:
        _check(backend.remove(job_id), f"could not remove the previous {NOW_NAME}")


def _check(proc, failure):
    if proc.returncode != 0:
        raise SystemExit(f"{failure}:\n{proc.stdout}\n{proc.stderr}")


def main(argv=None, backend=None, config_path=CONFIG_FILE):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # parse_args(None) on the CLI is sys.argv[1:], but in-process callers
    # pass [] so argparse never reads the test runner's argv.
    parser.add_argument("--now", action="store_true",
                        help="after registering, queue tonight's run as a one-shot a minute out")
    args = parser.parse_args(argv if argv is not None else [])

    if backend is None:
        if not os.path.exists(OPENCLAW[1]):
            raise SystemExit(f"{OPENCLAW[1]} not found -- run this inside the agent container")
        backend = CronBackend()

    owner_tz = load_owner_zone(config_path)
    start, window = load_memo(config_path)
    listing = backend.list()
    registered = registered_jobs(listing)
    desired = desired_jobs(start, window, owner_tz)
    paused = []

    for job in desired:
        current = registered.get(job["name"])
        if current is None:
            _check(backend.create(job), f"could not register {job['name']}")
            print(f"registered: {job['name']} ({job['schedule'] or 'every ' + job['every']})")
            continue
        if not current.enabled:
            print(f"WARNING: {job['name']} is registered but DISABLED -- it will never fire, and "
                  "this leaves it disabled rather than duplicating it. Enable it: "
                  f"{' '.join(OPENCLAW)} cron enable {current.id}")
            paused.append(job["name"])
        if not job_drift(job, current.spec):
            if current.enabled:
                print(f"already present, skipped: {job['name']}")
            continue
        _check(backend.edit(current.id, job), f"could not update drifted job {job['name']}")
        print(f"updated: {job['name']} ({job['schedule'] or 'every ' + job['every']})")

    wanted = {job["name"] for job in desired}
    for name, job in registered.items():
        if name not in wanted:
            _check(backend.remove(job.id), f"could not remove stale job {name}")
            print(f"removed stale job: {name}")

    if args.now:
        queue_now(backend, listing, window, owner_tz)

    if paused:
        raise SystemExit(
            f"registered what was missing, but {len(paused)} job(s) are DISABLED and will "
            f"never fire: {', '.join(paused)} -- {' '.join(OPENCLAW)} cron enable <id>")
    return 0


if __name__ == "__main__":
    # sys.argv[1:] explicitly: main(argv=None) parses [] on purpose, so the
    # CLI has to hand its arguments over itself, or no flag can ever be
    # passed from a terminal.
    sys.exit(main(sys.argv[1:]))
