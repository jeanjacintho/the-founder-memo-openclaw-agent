---
name: memo-schedule
description: The memo's cron spec — the nightly run at memo.start, the on-demand run and the recovery flusher — and the idempotent registration that replays them from pt/config.json. Use when asked to set up, re-register, inspect or repair the memo's crons, after rebuilding the agent's home, and after the start hour or window changes.
---

# The cron spec

Every row is derived from `/var/lib/plow/pt/config.json` at run time:

| job | schedule | notes |
|---|---|---|
| `memo-nightly` | `<min> <hour> * * *` from `memo.start` (default `01:00`) in `owner.timezone` | the night's run; its budget (`--timeout-seconds`) is `memo.window_minutes` (default 240) plus a 60-minute publish margin |
| `memo-deliver` | every minute | a **no-agent command job** (`--command-argv` running `post_to_chat.py --recover` with the venv's python; no model, no tokens). Resumes a posted memo's print or record that failed, without posting it again. The sweep never removes it; it drifts only on its command |
| `memo-now` | one-shot, a minute out | `register_crons.py --now`: tonight's run on demand, same prompt as `memo-nightly`; the next `--now` replaces it unless one is running (then nothing is queued); the sweep never removes it |

The job is an agent turn in an **isolated** session, on the chat's own model
(`PT_MODEL`), with delivery **none**: the scheduler never posts the run's final
text anywhere. The memo itself is posted by the run (`post_to_chat.py --pdf`),
to the owner's DM. The cron row carries `--tz` = `owner.timezone`, so the
scheduler fires on the owner's own wall clock, daylight saving included. The
window counts from when the run actually starts, not from the nominal hour.

The prompt hands the night to `memo-tournament`'s Start section, which takes
the workspace lock with `memo-shared/scripts/run_lock.py`: a manual
`openclaw cron run` beside the scheduled fire would otherwise write the same
scratch and deliver twice.

## Registering

**This is a bring-up step, not a repair step.** The scheduler keeps its jobs
in `/var/lib/plow/state/openclaw.sqlite`, on the state volume: they survive a
gateway restart and `docker compose up --build` (the volume is kept), and are
**gone on a fresh volume** — an instance brought up that way has a memo that
never runs, and nothing to diff against. Run it after any new state volume, at
the close of `memo-setup`, and after `memo.start` or `memo.window_minutes`
changes.

    /opt/plow/skills/memo-schedule/scripts/register_crons.py

**Then paste its output verbatim and report its exit status. The run is not
done until you have.** The script signals every refusal it has — a missing
or unusable config, a blank `owner.timezone`, a malformed `memo.start` or
`memo.window_minutes`, an unreadable or truncated job listing, a managed name
registered twice, a failed `cron add`, `edit` or `rm`, a registered-but-DISABLED
job — through its output and a non-zero exit, and a turn does not propagate an
exit code. Do not paraphrase, and do not call it done on a non-zero exit.

Create-if-missing, so it is safe to re-run: it reads what is already
scheduled from `openclaw cron list --all --json` (every job, disabled ones
included) and creates only what is absent. It also **reconciles drift**: a
registered job whose reported schedule, zone, prompt, model or run budget no
longer matches the spec is patched in place with `openclaw cron edit <id>`,
never removed and re-created. Drift is judged only against fields the
scheduler reported; an absent field is left alone. It removes a registered
`memo-*` job the spec no longer names, and never touches a job whose name does
not start with `memo-`: OpenClaw's own jobs in the same list (`heartbeat-main`,
memory dreaming, skill review) are never touched. **Hand-registering a job by
shell command instead of changing `memo.start` and re-running this script is
exactly the mistake this spec exists to make unnecessary.**

Two refusals are the whole reason this is a script and not a habit:

- **An unreadable, partial or unexpected job listing aborts** — a failed
  `cron list`, non-JSON, a wrong shape, or `hasMore`. Never read "I could not
  tell what is registered" as "nothing is" — that re-registers every job and
  duplicates all of them. A managed name registered twice is refused too.
- **`owner.timezone` must be nameable.** `memo.start` is the owner's clock and
  the job is registered in that zone.

A disabled job is neither skipped nor duplicated: it is left disabled (but
reconciled to the spec, so enabling it later does not bring back an old
schedule or budget), named with the command that enables it, and the run
exits non-zero after everything else finishes.

## Verifying an unattended run

From a turn (exec inherits the gateway token):

    node /app/openclaw.mjs cron list --all --json          # is the job there, and enabled?
    node /app/openclaw.mjs cron runs --id <job-id> --json  # then look for the memo in chat

Never force a paper job with `openclaw cron run`: queue `register_crons.py
--now` instead, which waits behind a run already in flight rather than racing
it. A run recorded as `skipped` with a provider-preflight error did not
research anything: OpenClaw retries only at the job's **next** scheduled time,
so queue tonight's run with `register_crons.py --now` once the provider answers
again.

A memo delivered unattended at least once is the bar: confirm the PDF in the
chat, not just that the cron fired — a run that completes with no memo is the
failure this whole skill exists to surface.

## Cutover from the previous paper scheduler

Setup records `memo.start`, a four-hour window and $100 ceiling. Existing
`delivery.*` configs migrate once, preserving owner, printer, signals and
priority preferences; the start is the old delivery hour minus its lead,
clamped at midnight. `priority.configured=false` or absent priority registers no nightly memo; migration removes obsolete `delivery` settings.
Only after every replacement is registered, reconciled and enabled are the
exact legacy `pt-daily-edition`, numbered editions, `pt-daily-edition-now` and
`pt-deliver` jobs retired by id. Other `pt-*` jobs are untouched. A failed or
disabled replacement leaves legacy jobs in place.

## Owner changes

Use `register_crons.py --start HH:MM` or `register_crons.py --enabled on|off`.
These commands validate and save preferences before reconciling jobs; do not
confirm a changed schedule if reconciliation fails. No direct config edit is needed.
