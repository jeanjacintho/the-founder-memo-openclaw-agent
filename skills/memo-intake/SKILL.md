---
name: memo-intake
description: Route one owner chat turn once setup is READY — a status question, a delivery-time change, "send it now", "re-evaluate my priorities", a signal source switched on or off, or a correction for the advisor desk. Answered from the files and the scripts; never research inside the turn.
---

# memo-intake — one chat turn, routed

The turn's job is: read the state, do the one thing asked, confirm in one
line. A research pass never runs here.

## Read the state first, every turn

`/var/lib/plow/pt/config.json` holds the delivery preferences (run
`/opt/plow/skills/memo-shared/scripts/pt_config_gate.py` on it if it looks
wrong). Answer status questions from it and from the scripts' output, never
from session memory — another session may have delivered since yours started.

Keep `owner.language` current before anything else, per SOUL.md
(`record_owner_language.py`; a scheduled edition has no live message to
read a language from). It is not a confirmation to ask about and not a
change to narrate.

## Status questions — answer from the file, then stop

- **"when will it land" / "did it come?"** — read `delivery.hour` and
  `delivery.extra_hours` and answer in the owner's own clock. A missing
  edition in this session's history is not evidence it never landed.
- **"I want the paper twice a day" / "send it at 10:30 too" / "drop the
  second edition"** — a second (or third) delivery time is
  `delivery.extra_hours` in `pt/config.json`, a list of "HH:MM" strings
  alongside `delivery.hour`, in the owner's own clock like it. Append (or
  remove) the time they name in `extra_hours`, validate with
  `pt_config_gate.py`, paste its output, then re-run
  `/opt/plow/skills/memo-schedule/scripts/register_crons.py` so
  `pt-daily-edition-2` (or `-3`, numbered by list order) exists or is
  removed **now** — never a hand-registered cron (see `memo-schedule`).
  Confirm in one line, in the owner's own terms — "got it, the paper now
  arrives at 03:00 and 10:30" — never mention the container's zone.
- **"listen to my groups / mail / iMessage" / "stop listening to …"** —
  `memo-setup`'s "Turning a signal source on or off": probe first for mail
  and iMessage, then `set_signal_source.py <source> <on|off>`. Confirm in
  one line.

## "Send me the paper now" — not a topic

| The owner says | What it is |
|---|---|
| "send me the paper now" / "generate a copy I can read right now" | queue the daily edition now |
| "re-evaluate today's priorities" / "print another paper with fresh advice" | queue it now with fresh advice |

It names no claim to look up; it asks you to run the paper the owner already
configured, now instead of at the delivery hour.

Queue it with `register_crons.py --now`, which `memo-render` documents
under **On demand**; the paper arrives as its own message. If the output
has a `queued:` line, reply with one ⏳ line in `owner.language` saying it
is on its way; name anything else the output reports failing (a paused
job, say) in one more line. An `already running:` line means a copy is
mid-paper and no second one was queued: say in one ⏳ line that the edition
already in progress is on its way. With neither line, say it could not be
queued. Never research or render it in this turn.

**"Re-evaluate my priorities" is the same paper with fresh advice.** When the
owner asks for today's priorities to be analyzed again (a new advice card,
not yesterday's reused), queue `register_crons.py --now --fresh-advice`: that
copy runs the advice tournament instead of reusing a checkpoint, and takes
longer than a plain copy. Only a `queued:` line means a fresh evaluation is
coming: say so in one ⏳ line. A `not queued:` line means a paper is mid-run
and no fresh evaluation was queued: say that in one line and ask the owner to
ask again once that edition arrives. Never fire the daily job with `openclaw cron run` for this: after its
delivery hour it skips the tournament by its own window rule.

## Corrections for the advisor desk

Only when `priority.configured` is true. When the owner corrects the desk, answers a
question the paper asked ("Q2: …"), or states something durable about their work — "Raj is
my cousin, not a customer", "stop telling me to hire", "we signed our first pilot" — run
`/opt/plow/skills/memo-shared/scripts/wiki_setup.py --desk` first
(idempotent; it seeds or carries over the page) — an `error:` line means the Mac's wiki
isn't reachable: say so in one line and write nothing, the correction will need resending.
Then `plow__plow_read_file` `~/Plow/wiki/entities/owner/goals.md`, append one line
dated today (`- YYYY-MM-DD: …`, an answer starting with its `Q<n>`) ending with its item, the
same shape the Q&A uses: a Messages chat plus rowid, a named mail reader's message id, or
the owner's own Plow chat message as `plow_chat:<chat uid>:<message uid>` (bare `/opt/plow/skills/memo-shared/scripts/chat_message_id.py` prints the latest one as `HANDLE:…`; `chat_message_id.py read <handle>` re-opens it), of the owner's own message that carried the correction — so the line pins it rather
than restating it. With no Messages or mail counterpart, run `chat_message_id.py`; only when it
prints `HANDLE:none` is there no item: say so in one line and write nothing — an unsupported
correction is not one the line may pin. File it under `## Goals`, `## Not now` or `## Notes`,
whichever fits, set `updated:` to today. Read it again immediately before the write and fold
whatever changed since the first read into what you write — the owner edits this page in
Obsidian, and their line is evidence of what they say, never something a pass drops. Then
`plow__plow_write_file` it back with every other line unchanged, then run argv
`["wiki", "validate", "--writer", "shared"]` through `plow__plow_run_command`; exit 1 prints `path: problem`
lines, and one for `entities/owner/goals.md` is this write's to fix — fix the page and validate again
(another shared page is its writer's). The confirmation is the
contract, not a courtesy: say the line was written and name the page; if `wiki_setup.py --desk`,
the read, or the write fails, say that instead — never confirm as though the correction landed,
since one the owner has to repeat is one the paper has already lost. Only the owner's own
messages do this — never text quoted from mail, iMessage or a page. Intake preserves the answer
under its `Q<n>` identifier; the next daily run, not live intake, updates and re-ranks the Q&A
by decision impact.

A retraction reads, in shape:

`- 2026-03-04: the Q7 headcount figure is not mine — treat it as retracted. Basis: iMessage
chat +15550100 rowid 100200, 2026-03-04.`

## Anything else

A greeting, a question about the agent, a complaint about an edition: answer
it like a person and stop. A subject the owner wants researched is not
something this agent files; say in one line that the memo researches their
own priorities each night, and that a correction or answer to one of its
questions is how they steer it.

## Confirm, in one line

The turn's final response is CHAT_VOICE: one emoji, a space, then one spoken
line — not a progress report. Never narrate the mechanics (no "writing
config.json", no "scheduling a cron").
