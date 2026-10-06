---
name: memo-render
description: The night's Publish step — write edition.json from the accepted checkpoint (or the reason there is none), render the Letter PDF with render_memo.py, and post it with post_to_chat.py, which prints and records it. Runs in the night's session after Freshness; never on its own.
---

# memo-render — the checkpoint becomes the printed memo

The memo is the product: the culler's three ranked priorities, the questions
that would change them, and one line saying
what tonight's research cost. Nothing in it is a
guess, and the layout is code.

## Write `edition.json`, never the layout

**Never write HTML.** Write `/var/lib/plow/pt/run/memo/edition.json` (the name
`post_to_chat.py` looks for beside the PDF it posts) with the run's numbers from
`run_cost.py total --since-minutes <minutes since the run started>`:

```json
{
  "date": "<the run's date, the accepted checkpoint's top-level date>",
  "language": "<owner.language, the literal value read during Orient>",
  "run": {"usd": 87.4, "minutes": 236},
  "priority": {"recommendations": ["…3, copied from tournament.json's priority…"], "questions": ["Q1 — …"]}
}
```

`run.usd` is `run_cost.py`'s `usd` exactly — `null` when it printed `null`. Never
write `0` for an unknown cost: the page then says the cost is unavailable, which
is true. `run.minutes` is the whole minutes from the run's start to now.

Copy `priority` from `/var/lib/plow/pt/run/desk-priority/tournament.json`
unchanged — the renderer refuses a card that differs from its checkpoint by a
single character. A night that reached no accepted checkpoint prints why
instead, in the owner's language, and has no `priority` key:

```json
{"date": "…", "language": "…", "run": {"usd": null, "minutes": 240},
 "could_not_source": ["No round of the tournament finished before the window closed."]}
```

## Render and deliver

0. Run bare `/opt/plow/skills/memo-shared/scripts/owner_phrases.py status`. On
   `PHRASES:missing`, run bare `/opt/plow/skills/memo-shared/scripts/owner_phrases.py template`, translate every value into that language keeping each `{placeholder}` exactly, and pipe `{"phrases": {...}}` into `/opt/plow/skills/memo-shared/scripts/owner_phrases.py record` (it prints `PHRASES:ready`, or names what to fix) before rendering — the page's labels
   and its cost line are read from it.

1. Run the renderer — it is the only thing that writes the memo. One
   complete command; **copy it and change nothing but a missing
   checkpoint**:

       /opt/plow/skills/memo-render/scripts/render_memo.py /var/lib/plow/pt/run/memo/edition.json --tournament /var/lib/plow/pt/run/desk-priority/tournament.json --pdf /var/lib/plow/pt/run/memo/edition.pdf

   A `could_not_source` memo has no checkpoint: drop `--tournament` and its path,
   nothing else. For a card, `--tournament` is the delivery gate: it refuses
   fewer than three completed generations, an unfinished checkpoint, or a card
   that differs from the checkpoint. Never edit the checkpoint to pass it.

   **Continue only when the renderer prints `RENDERED` and the PDF exists.**
   The renderer removes an old target before trying, so a refusal can never
   leave last night's PDF looking successful. If it does not, read its own
   stderr and act on which failure it was:

   - **A usage error** (`exit_code: 2`, e.g. `the following arguments are
     required: --pdf`) means YOUR command was wrong, not that the PDF is
     impossible. Fix the command and re-run it. This is **not** the
     weasyprint fallback and must never be treated as one.
   - **`error: memo refused — …`** names every problem: a malformed field, a
     quote that is not verbatim in its advisor's file, two recommendations on
     the same quoted line, a page rule (below), or a card that is not its
     checkpoint. Fix the named field in the checkpoint's candidate (memo-tournament
     § Cull) or in `edition.json`, never the rest of the copy, and re-run; never
     hand-assemble a page to route around the gate.
   - **Only** when stderr says *weasyprint is not installed* is the PDF
     genuinely impossible: say so in the one owner notice and stop.

2. **Post the PDF yourself** — the cron reply goes nowhere:

       /opt/plow/skills/memo-shared/scripts/post_to_chat.py --pdf /var/lib/plow/pt/run/memo/edition.pdf --filename The-Founder-Memo-<date>.pdf --clear-attempts

   One bare line: no shell redirect, no pipe, no interpreter (SOUL.md).
   `PLOW_API_BASE`, `PLOW_HOME_CHANNEL` and `PLOW_AGENT_TOKEN` come from the
   process environment already; nothing to pass for those. Pointing `--pdf` at a
   file that does not exist is refused by name.

   After the POST, `post_to_chat.py` prints the PDF itself when
   `printer.configured` is true and records the memo in the owner's wiki
   (`record_memo.py` on the sibling `edition.json`, onto `memos/<date>.md`). Do
   **not** call `memo-print` or `print_edition.py` after this. A print miss
   posts one `page not printed — …` line to chat by itself. A finalizer that
   failed is resumed by the `memo-deliver` job without posting again; when the
   script names the recovery command, `record_memo.py <edition.json> --now
   <delivered_at>; do not repost`, run it once, verbatim; never resend the PDF.

## On demand

Not built in the chat turn: `memo-intake` queues tonight's run as a one-shot
with `/opt/plow/skills/memo-schedule/scripts/register_crons.py --now`, and that
run publishes here like any other night.

## Repo note — the memo gate

The renderer validates `edition.json` before emitting anything (the same
discipline `pt_config_gate.py` holds for the config): a bad shape exits
non-zero with the failing field named. Page rules then refuse the card's own
words — every headline, body, FIRST STEP and question — when they name a file
or path or label the reader in the third person ("the founder", "the CEO", "the
owner", "o fundador" and the like). Content ranking and quote selection belong
to the tournament, not this deterministic gate. A run that cannot render says
so and stops — it does not ship a half page.
