#!/usr/bin/env python3
"""Register the memo's crons, idempotently, from pt/config.json.

Why this exists at all. The scheduler keeps its jobs in the gateway's state
volume; a fresh volume has none, and nothing else replays them. Keeping the
spec here, derived from pt/config.json, means "set up the crons" replays a
reviewed derivation instead of improvising schedules from a sentence.

The spec:

  pt-daily-edition       <min> <hour> * * *        one job; exists while
                         computed as                setup can register
                         delivery.hour -
                         lead_minutes (never
                         before midnight)
  pt-daily-edition-<n>   same, extra_hours         another run of the same
                         (n ≥ 2)                    paper later that day
  pt-daily-edition-now   one-shot, a minute out    --now: the paper on
                                                   demand, same prompt, no hold

Every cron job is registered with `--tz owner.timezone`: every stored hour --
delivery.hour, extra_hours -- is the owner's wall clock, and the scheduler
fires on it directly, daylight saving included.
post_to_chat.py's --hold-until waits on the same zone. Each job is an agent
turn in an isolated session with delivery `none`; the paper reaches chat
through post_to_chat.py.

This script therefore CREATES missing jobs and REMOVES the extra-hour jobs
the owner dropped. It never touches a job whose name does not start with pt-:
those are not this agent's to manage (OpenClaw keeps its own jobs, such as
its heartbeat, in the same list).

It also RECONCILES drift, which create-if-missing alone does not: a job
that is registered with a different schedule, zone, prompt or model than
the spec calls for is updated in place with `cron edit`. Drift is only
judged on a field the scheduler reported; a missing field is left alone
rather than edited on a guess. Never remove-then-create a drifted job: if
create failed after remove, the morning paper had no job until someone
reran the script.

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
from record_owner_language import _write_json  # noqa: E402 -- the config's atomic writer
from pt_paths import config_file, script  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from cron_backend import MODEL, OPENCLAW, PAPER_TIMEOUT_SECONDS, CronBackend  # noqa: E402 -- sibling module

CONFIG_FILE = str(config_file())
# The one daily-paper job. Owned and swept by name.
DAILY_NAME = "pt-daily-edition"
# A second (or third, ...) full-paper delivery time, from
# delivery.extra_hours -- same paper, re-researched and
# re-delivered at another hour of the same day. Numbered from 2 so the
# canonical DAILY_NAME reads as "the" edition and these read as its
# reruns, matching the lock-name convention (daily2-<date>, daily3-<date>)
# a hand-registered job already used before this existed as a real spec.
_EXTRA_DAILY_RE = re.compile(r"^pt-daily-edition-(?P<n>[2-9]\d*)$")
# The on-demand copy (--now): a one-shot the sweep below never removes, so
# a queued paper survives a registration run; the next --now replaces it.
NOW_NAME = "pt-daily-edition-now"
# The outbox's flusher: a scheduled paper that finishes before its delivery hour
# is staged in pt/outbox (post_to_chat.py --hold-until) instead of sleeping in
# its session, and this no-agent command job posts it once the hour comes. It
# runs every minute with no model and no tokens, is never swept, and drifts only
# on its command. The venv's python: a command job's PATH is the gateway's.
DELIVER_NAME = "pt-deliver"
DELIVER_ARGV = ["/opt/plow/pt-venv/bin/python3",
                "/opt/plow/skills/memo-shared/scripts/post_to_chat.py", "--flush-outbox"]
WORKSPACE_LOCK = "paper-workspace"
DEFAULT_LEAD_MINUTES = 0
# Every acquirer of a lock uses one lifetime. A run cannot outlive its scheduler
# budget (cron_backend.PAPER_TIMEOUT_SECONDS), and it takes the lock no earlier
# than it starts, so a lock older than the budget belongs to a run that is gone:
# one killed by a model error or by the budget itself, which never reaches its
# release. The margin covers the run's own wind-down. Every paper shares the
# workspace lock, so nothing shorter is safe: it could call a live run dead and
# start a competing paper.
STALE_RUN_MINUTES = PAPER_TIMEOUT_SECONDS // 60 + 20
# The closest two papers may start. The first can wait up to two lock rounds before it takes the
# lock and then be killed at its budget, so its lock is at most budget-minus-that-wait old when the
# second starts; the second's own two rounds add the wait back. Spacing papers at least the stale
# limit apart is what lets the second always reclaim an orphan, whatever the first waited.
# One more than the limit: takeover needs the lock strictly older than it (run_lock.py).
MIN_PAPER_SPACING_MINUTES = STALE_RUN_MINUTES + 1
# A scheduled paper that finds the workspace held (an on-demand copy runs its
# whole ~35-minute paper under the lock) waits two rounds of this before giving
# the day up: ~40 minutes, inside the hold-until window, each round under
# OpenClaw's 30-minute exec timeout. The plain on-demand copy never waits; a
# fresh-advice copy does.
HELD_LOCK_WAIT_SECONDS = 1200
# The priority desk's floor: with less than this left before delivery, a fresh
# three-generation tournament cannot finish (measured ~35-50 min) before the
# render and print still to follow. A delivery hour near midnight clamps the
# lead below it and nothing refuses that, so the prompt states the window and
# the desk writes its own reason instead of starting a tournament it cannot end.
MIN_TOURNAMENT_MINUTES = 50

DELIVERY_FAILURE_NOTICE = (
    "This is a paper execution, not a heartbeat: run the full paper pipeline. "
    "Do not finish the run before post_to_chat.py confirms the chat post or stages the edition. "
    "After that confirmation, finish with a short status for the cron run record; "
    "the cron reply is not delivered to chat. "
    "If any step stops, refuses or fails before post_to_chat.py confirms delivery, "
    "release the paper-workspace lock if you hold it, then send exactly one short "
    "message to the owner with message(action=send), channel plow, accountId chat, "
    "target plow-owner. Say the edition was not delivered and give the reason in "
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

def paper_prompt(hold_until=None, lead_minutes=0, fresh_advice=False):
    """The one run prompt every paper is built from, scheduled or on demand.

    Every paper shares one workspace lock because its desk scratch is shared.
    A scheduled paper reuses today's accepted advisor checkpoint when one
    exists, else runs the tournament.

    hold_until is the send clock (delivery.hour / an extra or focused hour).
    The job may start earlier via lead_minutes; POST must still wait. The
    on-demand copy (--now) passes none, posts when done, and never waits
    ~150 minutes on a tournament: it reuses the newest accepted checkpoint
    of any date, printed with its as-of date, and runs the tournament only
    when none has ever been accepted. fresh_advice (--now --fresh-advice) is
    the owner asking to re-evaluate today's priorities: that copy runs the
    tournament and reuses no checkpoint, since reusing one is what they
    asked it not to do.

    The prompt carries only what the run cannot read from its skills: the
    lock, the advice rule and the send clock. Delivery and print are
    memo-render step 2's, never restated here.
    """
    hold = (
        f", with --hold-until {hold_until} so chat waits for that clock "
        f"(if that hour has already passed, post immediately; never wait until tomorrow), "
        f"and with --clear-attempts"
        if hold_until else ", with --clear-attempts"
    )
    lock = script("memo-shared", "run_lock.py")
    advice = (
        "run the tournament now, whatever run/desk-priority/tournament.json holds: the owner "
        "asked to re-evaluate today's priorities, so reuse none, and no delivery hour bounds "
        "it. If it cannot reach an accepted checkpoint, the paper is not delivered: never "
        "print an unavailable advice card for a tournament that ran"
        if fresh_advice else
        "reuse today's accepted checkpoint in run/desk-priority/tournament.json when "
        f"there is one, else run the tournament -- this job starts {lead_minutes} minutes "
        f"before {hold_until} (delivery.lead_minutes, clamped so it never starts before "
        f"midnight); once the lock is yours, run {script('memo-shared', 'owner_time.py')} "
        f"minutes-until {hold_until} and, under {MIN_TOURNAMENT_MINUTES} minutes, record the "
        f"desk's unavailable reason with {script('memo-tournament', 'advice_unavailable.py')} window "
        f"--deliver-at {hold_until} --reason \"<why, in the owner's language>\" instead of "
        f"starting one; with {MIN_TOURNAMENT_MINUTES} minutes "
        f"or more, run the tournament"
        if hold_until else
        "reuse the newest accepted checkpoint in run/desk-priority/tournament.json whatever "
        "its date -- an older one prints with \"as_of\" per memo-render -- and run the "
        "tournament only if none has ever been accepted. An older checkpoint is never a "
        "reason to stop the paper; continue research and compile the edition with its as-of date"
    )
    attempts = script("memo-shared", "run_attempts.py")
    next_flag = " --scheduled" if hold_until else ""
    # A fresh-advice copy waits like a scheduled paper: it was promised to the owner, and
    # a paper that starts in the minute before it runs would otherwise end it at 'held'.
    waits = bool(hold_until) or fresh_advice
    wait = f" --wait-seconds {HELD_LOCK_WAIT_SECONDS}" if waits else ""
    if fresh_advice:
        # The tournament alone takes 35-50 minutes, so two rounds can end before a
        # paper that won the workspace in the scheduling gap lets go; its lock
        # goes stale on its own after STALE_RUN_MINUTES, which bounds this.
        held = (
            "run the same acquire again, and again for as long as it prints 'held' "
            "(each round waits; the other paper's lock expires on its own) -- never stop "
            "at 'held', the owner was promised this evaluation"
        )
    elif waits:
        held = (
            "run the same acquire once more; if that is also 'held', another paper owns "
            "the workspace -- stop"
        )
    else:
        held = "another paper owns the workspace -- stop"
    # One undated lock for the shared workspace: a dated name would give a paper that starts
    # after midnight a different lock from the one the earlier paper still holds (and a
    # fresh-advice copy waiting across midnight could take it), so two papers would archive and
    # write the same scratch. A stuck lock is reclaimed by age (STALE_RUN_MINUTES) as before.
    lock_arg = f"--name {WORKSPACE_LOCK}"
    return (
        f"{PAPER_RUN_MARKER} {SKILL_LOADING}"
        f"Run the daily edition now, in one session. First run {lock} acquire "
        f"{lock_arg} --stale-minutes {STALE_RUN_MINUTES}{wait}; "
        f"if its output is 'held', "
        f"{held}. Then run {attempts} begin{next_flag}: on 'proceed' go on; on 'stop' or "
        f"'stop-untold' the day's attempts are spent (retries after a provider rate limit only "
        f"feed it) and begin has told the owner, or tried to, itself -- run {lock} release "
        f"{lock_arg} and stop, writing nothing to the owner. Then "
        f"/opt/plow/skills/memo-shared/scripts/prepare_daily_run.py --preserve-priority "
        f"(it archives prior scratch after the lock; do not inspect or reuse old run files). "
        f"Then run the priority desk exactly as "
        f"memo-tournament/references/desk.md says ({advice}). "
        f"Then run memo-render for it, delivering with post_to_chat.py "
        f"per memo-render/SKILL.md step 2{hold}. "
        f"Release the lock with {lock} release {lock_arg}. "
        f"{DELIVERY_FAILURE_NOTICE}"
    )


def load_owner_zone(config_path=CONFIG_FILE):
    """owner.timezone, or refuse: every schedule here is written against it."""
    path = pathlib.Path(config_path)
    try:
        config = json.loads(path.read_text())
        owner = config["owner"]["timezone"]
    except FileNotFoundError:
        raise SystemExit(
            f"refusing to register: {path} is missing. memo-setup writes it; "
            "its owner.timezone is what every schedule here is written against."
        ) from None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(
            f"refusing to register: could not read owner.timezone from {path} "
            f"({exc!r})."
        ) from exc
    if not str(owner or "").strip():
        raise SystemExit(
            f"refusing to register: {path} has a blank owner.timezone."
        )
    return owner


def adopt_owner_clock(owner_tz, legacy_tz, config_path=CONFIG_FILE):
    """Retire delivery.local_hour, left by an older setup that stored
    delivery.hour on the previous runtime's container clock (legacy_tz, that
    install's TZ). With one zone that hour already is the owner's; across two
    zones it is not recoverable without guessing through offsets.
    """
    path = pathlib.Path(config_path)
    config = json.loads(path.read_text())
    if "local_hour" not in config["delivery"]:
        return
    if owner_tz != legacy_tz:
        raise SystemExit(
            f"refusing to register: {path} predates owner-clock hours and its times "
            f"are on the old container clock ({legacy_tz}), not the owner's "
            f"({owner_tz}). Ask the owner for their delivery time, extra hours and "
            "paper times again, write them as their own clock, remove "
            "delivery.local_hour, and re-run.")
    del config["delivery"]["local_hour"]
    _write_json(path, config)


def load_delivery_hour(config_path=CONFIG_FILE):
    """delivery.hour from pt/config.json -- its exact 'HH:MM' shape is the
    gate's contract; both parts feed the schedule."""
    path = pathlib.Path(config_path)
    try:
        config = json.loads(path.read_text())
        return str(config["delivery"]["hour"])
    except FileNotFoundError:
        raise SystemExit(
            f"refusing to register: {path} is missing -- memo-setup owns it"
        ) from None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"refusing to register: malformed {path} ({exc!r}).") from exc


def load_extra_hours(config_path=CONFIG_FILE):
    """delivery.extra_hours from pt/config.json -- additional full-paper
    delivery times the same day, each "HH:MM" like delivery.hour itself.

    Optional and defaults to empty: an install with one delivery time a day
    (the common case) has no extra_hours key at all, and a schedule that
    refused to compute without it would strand a working agent. The gate
    validates each entry's shape when the key is present; this just reads
    it back, in order (order is the slot numbering -- pt-daily-edition-2 is
    always extra_hours[0]).
    """
    path = pathlib.Path(config_path)
    try:
        config = json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(
            f"refusing to register: {path} is missing -- memo-setup owns it"
        ) from None
    except (OSError, ValueError) as exc:
        raise SystemExit(f"refusing to register: malformed {path} ({exc!r}).") from exc
    hours = config.get("delivery", {}).get("extra_hours") or []
    if not isinstance(hours, list) or not all(isinstance(h, str) for h in hours):
        raise SystemExit(
            f"refusing to register: {path} has delivery.extra_hours={hours!r}; "
            "it must be a list of \"HH:MM\" strings."
        )
    return hours


def load_lead_minutes(config_path=CONFIG_FILE):
    """delivery.lead_minutes from pt/config.json, defaulting to 0.

    The key is optional on purpose (the gate only validates it when present):
    an install written before the personalized paper existed has no
    lead_minutes, and a schedule that refuses to compute for it would strand
    a working agent. Absent means the default, not an error.
    """
    path = pathlib.Path(config_path)
    try:
        config = json.loads(path.read_text())
        raw = config.get("delivery", {}).get("lead_minutes", DEFAULT_LEAD_MINUTES)
    except FileNotFoundError:
        raise SystemExit(
            f"refusing to register: {path} is missing -- memo-setup owns it"
        ) from None
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        raise SystemExit(f"refusing to register: malformed {path} ({exc!r}).") from exc
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise SystemExit(
            f"refusing to register: {path} has delivery.lead_minutes={raw!r}; "
            "it must be a non-negative integer (minutes before delivery.hour)."
        )
    return raw


def _hour_minute(delivery_hour):
    """Parse a gate-shaped "HH:MM" into (hour, minute) ints."""
    hour_part, minute_part = delivery_hour.split(":")
    return int(hour_part), int(minute_part)


def _minutes(hhmm):
    hour, minute = _hour_minute(hhmm)
    return hour * 60 + minute


def _lead(hour, lead_minutes):
    """The lead for one owner-clock hour, clamped so the run never starts
    before midnight -- the run's lock and paper are dated in the owner's zone."""
    return min(lead_minutes, _minutes(hour))


def daily_schedule(delivery_hour, lead_minutes):
    """The daily paper's cron expression, on its delivery day.

    delivery.hour is any real "HH:MM" (the gate's contract). The lead is
    subtracted in minutes from the OWNER's chosen minute, not just the hour.
    A lead reaching back past midnight is refused: that run would fire the
    evening before and be the previous day's paper. Every job's schedule
    comes through here, so this is the one place that refuses it.
    """
    total = _minutes(delivery_hour) - lead_minutes
    if total < 0:
        raise SystemExit(
            f"refusing to register: delivery.lead_minutes={lead_minutes} would start "
            f"the {delivery_hour} run before midnight of its delivery day.")
    return f"{total % 60} {total // 60} * * *"


def daily_job(delivery_hour, lead_minutes, owner_tz, *, name=DAILY_NAME):
    """One full-paper delivery job -- the canonical slot, or an extra one."""
    return {
        "name": name,
        "schedule": daily_schedule(delivery_hour, lead_minutes),
        "tz": owner_tz,
        "prompt": paper_prompt(hold_until=delivery_hour, lead_minutes=lead_minutes),
    }


def deliver_job():
    """The one job every install has besides its papers: pt-deliver."""
    return {"name": DELIVER_NAME, "every": "1m", "schedule": None, "tz": None,
            "prompt": None, "command": DELIVER_ARGV}


def require_workspace_spacing(hours, lead_minutes=DEFAULT_LEAD_MINUTES):
    """Refuse paper starts whose shared-workspace windows can overlap.

    Compared on the jobs' real cron start times: a lead clamped at midnight pulls a late-night
    paper's start toward its neighbour, so two delivery hours far enough apart can still start close."""
    minimum_minutes = MIN_PAPER_SPACING_MINUTES
    starts = {hour: _minutes(hour) - _lead(hour, lead_minutes) for hour in hours}
    for index, first in enumerate(hours):
        for second in hours[index + 1:]:
            distance = abs(starts[first] - starts[second])
            if min(distance, 24 * 60 - distance) < minimum_minutes:
                raise SystemExit(
                    f"refusing to register: paper times {first} and {second} are less than "
                    f"{minimum_minutes} minutes apart; their shared workspace can overlap."
                )


def desired_jobs(delivery_hour, owner_tz,
                 lead_minutes=DEFAULT_LEAD_MINUTES, extra_hours=()):
    """The jobs the config calls for, in spec order.

    The daily edition comes first, then one job per extra delivery time
    (delivery.extra_hours -- the same paper, re-run later the same day).
    Hours are the owner's and register in the owner's zone; lead_minutes is
    the nominal lead, clamped per slot (see _lead).
    """
    require_workspace_spacing([delivery_hour, *extra_hours], lead_minutes=lead_minutes)
    jobs = [daily_job(delivery_hour, _lead(delivery_hour, lead_minutes), owner_tz)]
    for n, hour in enumerate(extra_hours, start=2):
        jobs.append(daily_job(hour, _lead(hour, lead_minutes), owner_tz, name=f"{DAILY_NAME}-{n}"))
    return jobs


def stale_names(registered, extra_hours_count=0):
    """Registered pt-* jobs the spec no longer calls for.

    The daily job is never stale; a numbered extra-daily job goes stale the
    moment the owner removes that many delivery times. Names not starting
    with pt- are never ours to remove.
    """
    return [name for name in registered
            if (m := _EXTRA_DAILY_RE.fullmatch(name)) and int(m.group("n")) > extra_hours_count + 1]


def registered_jobs(listing):
    """{name: job} for the pt-* jobs this spec manages, from a full listing.

    A managed name registered twice is refused rather than guessed at --
    editing or sweeping one of two copies leaves the other firing. The
    on-demand copy (pt-daily-edition-now) is the exception: queue_now
    replaces it by id.
    """
    registered = {}
    for job in listing:
        if not job.name.startswith("pt-") or job.name == NOW_NAME:
            continue
        if job.name in registered:
            raise SystemExit(
                f"refusing to register: {job.name} is registered twice "
                f"({registered[job.name].id}, {job.id}). Remove one with "
                f"`{' '.join(OPENCLAW)} cron rm <id>` and re-run.")
        registered[job.name] = job
    return registered


def _same_schedule(want, have, cron):
    if cron:
        return want == have
    try:  # one-shots come back normalized to UTC; compare the instant
        return datetime.fromisoformat(want).timestamp() == datetime.fromisoformat(
            have.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, AttributeError):
        return want == have


def job_drift(job, spec):
    """True when a registered job's reported fields contradict the spec.

    Only a field that is BOTH reported and different is a drift; an absent
    field is silence, not a mismatch. Schedule, zone, prompt and model are
    the fields a spec change actually moves (the delivery hour, the owner's
    zone, the lead, the delivery contract, the model the paper is tuned on).
    The run budget is the exception: a job registered before it was set reports
    no timeout at all, which is the scheduler's 60-minute default, so a reported
    spec with no timeout drifts and the next register moves it.
    """
    if job.get("command") is not None:  # a command job has no prompt or model
        return spec.get("command") is not None and spec["command"] != job["command"]
    if "timeout" in spec and spec["timeout"] != PAPER_TIMEOUT_SECONDS:
        return True
    for key in ("schedule", "tz", "prompt", "model"):
        have = spec.get(key)
        want = job.get(key, MODEL) if key == "model" else job.get(key)
        if have is None or want is None:
            continue
        if key == "schedule":
            if not _same_schedule(want, have, cron=job.get("tz") is not None):
                return True
        elif have != want:
            return True
    return False


def _is_paper(name):
    """A job that runs a paper under the workspace lock."""
    return name in (DAILY_NAME, NOW_NAME) or bool(_EXTRA_DAILY_RE.fullmatch(name))


def queue_now(backend, listing, lead_minutes, owner_tz, clock=None, fresh_advice=False):
    """The on-demand copy: the main paper's own prompt as a one-shot job.

    The scheduler fires it exactly like the morning run -- its own session,
    the same workspace lock, the same delivery leg -- so "send me the paper
    now" can never be a thinner or different paper. Previous copies are
    removed by id only after the new one is created, so a failed create
    never cancels a copy the owner was already promised. A copy that is
    running is left alone and no second one is queued: `cron rm` aborts its
    session mid-paper, the workspace lock outlives it, and every later copy
    reads 'held' and stops until the lock goes stale. The same holds for any
    paper mid-run: a copy queued behind it reads 'held' and stops. So while
    one runs, a fresh-advice request queues nothing and says so -- the running
    paper reuses its checkpoint, so its edition is not the fresh evaluation.
    """
    running = [j for j in listing if _is_paper(j.name) and j.running]
    if running and fresh_advice:
        print(f"not queued: {running[0].name} ({running[0].id}) is mid-paper -- "
              "no fresh evaluation was queued; ask again once it is delivered")
        return
    if running:
        print(f"already running: {running[0].name} ({running[0].id}) -- its edition is on the way")
        return
    at =(clock or datetime.now(ZoneInfo(owner_tz))) + timedelta(minutes=1)
    job = {
        "name": NOW_NAME,
        "schedule": at.isoformat(timespec="seconds"),
        "tz": None,
        "prompt": paper_prompt(lead_minutes=lead_minutes, fresh_advice=fresh_advice),
    }
    previous = [j.id for j in listing if j.name == NOW_NAME]
    _check(backend.create(job), f"could not queue {NOW_NAME}")
    print(f"queued: {NOW_NAME} ({job['schedule']})")
    for job_id in previous:
        _check(backend.remove(job_id), f"could not remove the previous {NOW_NAME}")


def _check(proc, failure):
    if proc.returncode != 0:
        raise SystemExit(f"{failure}:\n{proc.stdout}\n{proc.stderr}")


def main(argv=None, backend=None, config_path=CONFIG_FILE, env=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # parse_args(None) on the CLI is sys.argv[1:], but in-process callers
    # pass [] so argparse never reads the test runner's argv.
    parser.add_argument(
        "--now", action="store_true",
        help="after registering, queue the main paper as a one-shot a minute "
             "out -- the on-demand copy, same prompt, no send clock",
    )
    parser.add_argument(
        "--fresh-advice", action="store_true",
        help="with --now: the owner asked to re-evaluate today's priorities, so the "
             "copy runs the advice tournament instead of reusing a checkpoint",
    )
    args = parser.parse_args(argv if argv is not None else [])
    if args.fresh_advice and not args.now:
        parser.error("--fresh-advice is an option of --now")
    env = os.environ if env is None else env

    if backend is None:
        if not os.path.exists(OPENCLAW[1]):
            raise SystemExit(f"{OPENCLAW[1]} not found -- run this inside the agent container")
        backend = CronBackend()

    owner_tz = load_owner_zone(config_path)
    adopt_owner_clock(owner_tz, (env.get("TZ") or "").strip() or owner_tz, config_path)
    delivery_hour = load_delivery_hour(config_path)
    extra_hours = load_extra_hours(config_path)
    lead_minutes = load_lead_minutes(config_path)

    listing = backend.list()
    registered = registered_jobs(listing)
    paused = []
    pending = []

    for job in [*desired_jobs(delivery_hour, owner_tz, lead_minutes, extra_hours), deliver_job()]:
        current = registered.get(job["name"])
        if current is not None:
            if not current.enabled:
                print(
                    f"WARNING: {job['name']} is registered but DISABLED -- it will "
                    "never fire, and this leaves it disabled rather than "
                    f"duplicating it. Enable it: {' '.join(OPENCLAW)} cron enable {current.id}"
                )
                paused.append(job["name"])
                # Still brought up to the spec (budget included), so enabling it later
                # does not bring back an old job.
                if job_drift(job, current.spec):
                    pending.append(("edit", job, current))
                continue
            if not job_drift(job, current.spec):
                print(f"already present, skipped: {job['name']}")
                continue
            pending.append(("edit", job, current))
        else:
            pending.append(("create", job, None))

    for action, job, current in pending:
        if action == "edit":
            print(
                f"updating drifted job: {job['name']} "
                f"(was {current.spec.get('schedule')!r} {current.spec.get('tz')!r}, "
                f"now {job['schedule'] or job.get('every')!r} {job['tz']!r})"
            )
            _check(backend.edit(current.id, job), f"could not update drifted job {job['name']}")
            print(f"updated: {job['name']} ({job['schedule'] or 'every ' + job['every']})")
        else:
            _check(backend.create(job), f"could not register {job['name']}")
            print(f"registered: {job['name']} ({job['schedule'] or 'every ' + job['every']})")

    for name in stale_names(registered, len(extra_hours)):
        _check(backend.remove(registered[name].id), f"could not remove stale job {name}")
        print(f"removed stale job: {name}")

    if args.now:
        queue_now(backend, listing, lead_minutes, owner_tz, fresh_advice=args.fresh_advice)

    if paused:
        raise SystemExit(
            f"registered what was missing, but {len(paused)} job(s) are "
            f"DISABLED and will never fire: {', '.join(paused)} -- "
            f"{' '.join(OPENCLAW)} cron enable <id>"
        )
    return 0


if __name__ == "__main__":
    # sys.argv[1:] explicitly: main(argv=None) parses [] on purpose, so the
    # CLI has to hand its arguments over itself, or no flag can ever be
    # passed from a terminal.
    sys.exit(main(sys.argv[1:]))
