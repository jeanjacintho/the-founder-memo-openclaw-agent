---
name: memo-schedule
description: The memo's cron spec — the daily job, its extra delivery hours and the outbox flusher — and the idempotent registration that replays them from pt/config.json. Use when asked to set up, re-register, inspect or repair the paper's crons, after rebuilding the agent's home, and after a delivery time changes.
---

# The cron spec

Every row is derived from `/var/lib/plow/pt/config.json` at run time:

| job | schedule | notes |
|---|---|---|
| `pt-daily-edition` | `<min> <hour> * * *`, computed as `delivery.hour − delivery.lead_minutes` (default 0) in the owner's zone, never before that day's midnight | one job; the paper. Cron may start early; `post_to_chat.py --hold-until` is the send clock |
| `pt-daily-edition-<n>` (n ≥ 2) | same computation, against `delivery.extra_hours[n-2]` | the **same** paper again later the same day |
| `pt-deliver` | every minute | the outbox's flusher: a **no-agent command job** (`--command-argv` running `post_to_chat.py --flush-outbox` with the venv's python; no model, no tokens). Posts each staged paper once its hour has come. Every install has it; the sweep never removes it; it drifts only on its command |
| `pt-daily-edition-now` | one-shot, a minute out | `register_crons.py --now`: the main paper on demand, same prompt as `pt-daily-edition` without `--hold-until`; the next `--now` replaces it unless it is running (then nothing is queued), the sweep never removes it; `--now --fresh-advice` runs the advice tournament instead of reusing a checkpoint |

The daily schedule is computed in minutes, so `00:00 − 0min` is `0 0 * * *`
(midnight itself). A lead that would reach back past midnight, such as
`00:00 − 20min`, is refused: that run would be the previous day's paper.

Every row is an agent turn in an **isolated** session, on the chat's own
model (`PT_MODEL`: `plow/openai/gpt-6-sol` on Plow, `openai/gpt-6-sol` on the
owner's OpenAI account), with delivery
**none**: the scheduler never posts the run's final text anywhere. The edition
itself is posted mid-run as the PDF plus any chat-only mail/sports companion
(`post_to_chat.py --pdf --text-file`), to the owner's DM (`PLOW_HOME_CHANNEL`, or `owner_chat.py`
when boot did not know it yet). Every cron row carries `--tz` =
`owner.timezone`, so the scheduler fires on the owner's own wall clock,
daylight saving included; one-shots carry an ISO time with its offset.
Scheduled papers add `--hold-until` at that job's hour (read on the same
owner clock) so a recipe that finished early does not send before the clock;
the on-demand copy has none. Nothing waits in a session for that hour: the
paper is staged in `pt/outbox/` and `pt-deliver` posts it (a session sleeping
until the hour is killed by the exec timeout).

The daily run additionally takes a **run lock** with
`memo-shared/scripts/run_lock.py` (see the prompt this script writes): two runs
at once — a manual `openclaw cron run` beside the scheduled fire — would
otherwise write the same desk scratch and deliver twice. The lock is a file created with O_EXCL, so the two runs agree on
one owner.

## Registering

**This is a bring-up step, not a repair step.** The scheduler keeps its jobs
in `/var/lib/plow/state/openclaw.sqlite`, on the state volume: they survive a
gateway restart and `docker compose up --build` (the volume is kept), and are
**gone on a fresh volume** — an instance brought up that way has
a paper that never fires, and nothing to diff against, because the
failure looks identical to a producer running and finding nothing. Run it
after any new state volume, at the close of `memo-setup` (so the first
paper's job exists as soon as setup ends), and after a delivery time
changes.

    /opt/plow/skills/memo-schedule/scripts/register_crons.py

**Then paste its output verbatim and report its exit status. The run is not
done until you have.** The script signals every refusal it has — a missing
or unusable config, a blank `owner.timezone`, an unreadable or truncated job
listing, a managed name registered twice, a failed `cron add`, `edit` or `rm`,
a registered-but-DISABLED job — through its output and a non-zero exit, and a
turn does not propagate an exit code. If you summarise instead of pasting,
"set up the crons, though one was paused" is an honest sentence describing a
run that failed, and nobody can tell. Do not paraphrase, and do not call it
done on a non-zero exit.

Create-if-missing, so it is safe to re-run: it reads what is already
scheduled from `openclaw cron list --all --json` (every job, disabled ones
included — a plain `cron list` hides them) and creates only what is absent.
It also **reconciles drift**: a registered job whose reported schedule,
zone, prompt, model or run budget (`--timeout-seconds`, three hours: the scheduler's own
60-minute watchdog would otherwise abort a slow paper with its lock held) no longer matches the spec — the owner changed the
delivery hour, the lead or their zone, the prompt's contract moved — is
patched in place with `openclaw cron edit <id>`, never removed and
re-created. Without that, "already present, skipped" would mean a changed
delivery hour is silently ignored forever. Drift is judged only against
fields the scheduler reported; an absent field is left alone, not edited on
a guess (one-shot times are compared as instants: the scheduler stores them
in UTC).
It removes `pt-daily-edition-<n>` whose number exceeds the current
`delivery.extra_hours` count. The canonical `pt-daily-edition` stays
registered after setup. It never touches a job whose name is not one of
`pt-daily-edition`, `pt-daily-edition-<n>`, `pt-deliver` or
`pt-daily-edition-now`: those are not this spec's to interpret or remove —
**hand-registering a job by shell command instead of writing
`delivery.extra_hours` and re-running this script is exactly the mistake
this spec exists to make unnecessary**: such a job is invisible to this
sweep forever. OpenClaw's own jobs in the same list
(`heartbeat-main`, memory dreaming, skill review) are never touched. Registration never deletes runtime locks or
run evidence; stale takeover belongs to `run_lock.py`, and evidence cleanup
belongs to the producer that knows when its consumers are finished.

Two refusals are the whole reason this is a script and not a habit:

- **An unreadable, partial or unexpected job listing aborts** — a failed
  `cron list`, non-JSON, a wrong shape, or `hasMore` (a truncated page).
  Never read "I could not tell what is registered" as "nothing is" — that
  re-registers every job and duplicates all of them. A managed name
  registered twice is refused too: editing or sweeping one of two copies
  leaves the other firing.
- **`owner.timezone` must be nameable.** Stored hours are the owner's clock
  and every job is registered in that zone. A config still carrying
  `delivery.local_hour` (an install from the previous runtime, whose hours
  were on its container clock) has that key dropped when that old `TZ` —
  if the environment still names it — equals `owner.timezone`; otherwise the
  script refuses and names how to re-state the owner's times.

A disabled job is neither skipped nor duplicated: it is left disabled (but
reconciled to the spec like any other, so enabling it later does not bring
back an old schedule or run budget), named with the command that enables it,
and the run exits non-zero after everything else finishes.

## Verifying an unattended run

From a turn (exec inherits the gateway token):

    node /app/openclaw.mjs cron list --all --json        # is the job there, and enabled?
    node /app/openclaw.mjs cron run <job-id> --json      # force one (never a paper job)
    node /app/openclaw.mjs cron runs --id <job-id> --json  # then look for the edition in chat

Never force a paper job (`pt-daily-edition`, `pt-daily-edition-<n>`) this way: past its
delivery hour the window rule skips the advice tournament, so the copy prints
no fresh advice. To re-run the paper, queue a copy with `register_crons.py --now`,
or `--now --fresh-advice` when the owner asked to re-evaluate priorities.

A forced run exercises the whole path a nightly fire would take once it
starts; its `runId` starts with `manual:`. Only a scheduled fire proves the
schedule itself. A run recorded as `skipped` with a provider-preflight error
did not research anything: OpenClaw retries only at the job's **next**
scheduled time, so for the daily paper queue the day's copy with
`register_crons.py --now` once the provider answers again.

A paper delivered unattended at least once is the bar: confirm the
edition in the chat, not just that the cron fired — a run that completes with no edition is the failure this whole
skill exists to surface.
