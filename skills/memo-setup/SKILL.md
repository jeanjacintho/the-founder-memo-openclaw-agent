---
name: memo-setup
description: First-run conversation over chat — the start hour, a printer probed once through Latch, and whether the Mac stays awake at night — then the owner's timezone from Latch location, the config, and the one-off first read of their company. Use on the owner's first DM, including greetings (oi, oi de novo, hi, hello, hey), while pt/config.json is missing owner.timezone, memo.start or printer.configured. Never ask their name or a personal profile, nor their timezone while their Mac is connected. Never in a group, never in someone else's DM, and never to change one already-stored setting.
---

# memo-setup — the first conversation

**No Mac?** If this turn has no Mac (Latch) tools (`plow__plow_run_command`,
`plow_browser`) or says the owner's Mac (Latch) is not connected:
- Ask only the start hour. In that same `record_setup.py` call add
  `printer.configured=false mac.awake=false`: never ask about a printer or Keep
  Mac Awake. Say in one line that the memo arrives here in chat.
- At close, ask the owner once which city or time zone they are in, then
  finalize with that place's IANA zone (Close, step 1).
- Never say the memo can't be scheduled because the Mac can't report a location.

There is no interview. The memo learns the company by reading the owner's Mac,
not by asking: setup settles when it runs, whether it can print, and whether
the Mac will be awake to read, then hands over to the first read.
`/var/lib/plow/pt/config.json` and `/var/lib/plow/pt/.setup-draft.json` are
the **only** record of how far it got — not the Plow Chat thread. Older
messages about a printer after a wiped session are leftover; if the draft is
missing, start at the hour. Do **not** ask their timezone — Latch location at
the end supplies `owner.timezone` (without a Mac, the close step says how). Never re-ask something the draft or config
already holds.

**Every draft write, and every "what's next", goes through one script —
never a hand-edited `.setup-draft.json`, never your own judgement about
which question comes after which:**

    /opt/plow/skills/memo-shared/scripts/record_setup.py /var/lib/plow/pt/config.json key=value [key=value ...]

One line, no interpreter prefix, no shell operators — same rule SOUL.md
gives `setup_needed.py`. `key` is a dot-path (`start`, `owner.language`,
`printer.configured`, `printer.name`, `mac.awake`);
`true`/`false` become real JSON booleans, anything else stays a string. A
value with a space needs its own quoting, e.g. `printer.name="HP LaserJet 4"`.
It prints two lines:

    DRAFT:<fields already recorded>
    NEXT_QUESTION=<hour|printer|awake|close>

**Send exactly the one message `NEXT_QUESTION` calls for, then stop.**
Not that question plus the probe for the one after it. Not that question
plus a summary of what you just recorded. One question, one reply, then
wait for the owner. The questions below are written in two parts for
exactly this reason: part **a** is what you send and then stop for; part
**b** is what you do on their *next* message, before sending the
question after it.

**This interview never needs ad-hoc Python**, a heredoc, or any inline
script, for anything (SOUL.md): every action already has a named script
(`setup_needed.py`, `record_setup.py`, `pt_config_gate.py`) or a named tool
(`plow_run_command`, `plow_browser_*`). If you feel any pull to "just
check" something, re-read the current step instead.

Send the message the step calls for — **and only that message** —
in CHAT_VOICE (SOUL.md), answering what the owner actually said first.

**Slow work needs a hang-on, not a play-by-play.** Before any Latch call
or Mac file write, and again after every `plow_get_result` poll, run this
bare:

    /opt/plow/skills/memo-shared/scripts/chat_status.py --busy

It POSTs at most two ⏳ lines ("tô nessa", then "ainda nisso" if it is
still going). The first call after each message the owner sends is
`chat_status.py --busy --new-wave`: their answer starts a new wait, which gets
its own hang-on even when the last one was minutes ago; the polls inside that
wait stay a bare `--busy`. `STATUS:too-early` / `STATUS:already` is success; keep
working. Never type "checking the printer", "writing a file", a URL, or
a tool name.

**A greeting is this interview.** "oi", "oi de novo", "hi", "hello", "hey"
with a missing config is the opener below, not a hello-plus-help-menu and
not a continuation of a profile interview that already happened in this
chat.

**Opener — send this, then stop and wait.** Copy it. Match the owner's language.
Portuguese:

> 📰 Oi! Eu sou o The Founder Memo: toda noite eu leio seu e-mail, mensagens e agenda e de manhã as três prioridades que mais importam saem impressas. A que horas eu começo? Se não disser nada, começo à 1h.

English:

> 📰 Hi — I'm The Founder Memo: every night I read your mail, messages and calendar, and in the morning the top three priorities are printed. What time should I start? If you don't say, I'll start at 1:00.

**Changing one setting later** is not this skill: a different start hour
(`memo.start`, the owner's own clock — never ask the zone again), **turning a
signal source on or off** (see below), or a new printer is a one-line
conversation that updates `pt/config.json` directly. After a valid change,
re-run the gate and then re-run
`/opt/plow/skills/memo-schedule/scripts/register_crons.py` so the
new schedule exists now — not an interview from the top, and never a
hand-registered cron (see `memo-schedule`).

**Turning a signal source on or off** after setup is one bare call,
never a hand-edited config:

    /opt/plow/skills/memo-shared/scripts/set_signal_source.py group_chat on
    /opt/plow/skills/memo-shared/scripts/set_signal_source.py email on
    /opt/plow/skills/memo-shared/scripts/set_signal_source.py imessage on

(`off` to stop). Every source starts off. Before `email on`, probe Google with
`plow_run_command` argv `["plow-gog", "gmail", "search", "newer_than:1d", "--max", "5", "--json", "--fields", "id,date,from,subject"]`;
before `imessage on`, probe once through Latch with **exactly** the argv the
nightly scan uses, so the Mac's "always allow" covers the unattended runs:

```json
{ "argv": ["plow-messages", "search", "--limit", "200", "--order", "desc"], "read_paths": ["~/Library/Messages"], "goal": "Read incoming iMessages for the paper's priority signals" }
```

A result (even zero rows) works; `blocked`, an error or an unreachable Mac
switches nothing on. It prints `SIGNALS:group_chat=…,email=…,imessage=…`;
confirm in one line. No cron changes: the night reads the switches itself.

## The questions, in order

Start of turn, every turn while `SETUP_NEEDED`: `setup_needed.py`'s second
line (`DRAFT:...`) or `record_setup.py`'s own `NEXT_QUESTION` from the
answer you just recorded says which of these you are on. Never infer it
from the draft's shape yourself, and never from what the chat thread
already discussed.

**1a. Ask the start hour, nothing else** — but only if the message
you are answering right now is a bare greeting ("oi", "hi", "hello")
with nothing else in it. **If it already reads like an hour answer
(see 1b's list), skip straight to 1b — do not send this question
again just because the draft still says `DRAFT:none`.** Otherwise: copy the locked hour line. Do not ask a
city, a zone, or a fuso — you will read that from Latch at the end. Send
only this, then stop.

Portuguese:

> 🕐 A que horas eu começo a ler, à noite? Se não disser nada, começo à 1h.

English:

> 🕐 What time should I start reading at night? If you don't say, I'll start at 1:00.

**1b. On their next message**, treat any of "yes", "y", "sim", "ok",
"okay", "that", "default", "1", "1am", "1h", "1:00", "01:00", "pode", "isso", or
a skip as accepting 01:00; a time they name ("2am", "23:30", a bare "2") is
that time on a 24-hour clock, written `HH:MM` ("2am" → `02:00`, "11pm" →
`23:00`). Record it and read the next question:

    record_setup.py /var/lib/plow/pt/config.json start=01:00 owner.language=English

**Record `owner.language` in this same call**, as a plain-English name
("English", "Portuguese", "Mandarin Chinese"), read from what the owner
has actually written so far — not from this file's language, not from
their name, not from where they are. From here on the gate prints it back
as `LANG:` (SOUL.md).

**No Mac?** (the block at the top) There is no printer to probe and no Mac to keep awake: add
`printer.configured=false mac.awake=false` to this same call, say in one line,
in their language, that the memo arrives here in chat, and go straight to the
close step (`NEXT_QUESTION` says `close`).

Send only the `NEXT_QUESTION` it prints (question 2a), then stop. Do not
also probe the printer in this reply — that happens on their *next*
message, in 2b, never before question 2a has actually been sent to them.
Do not write `pt/config.json` yet: `owner.timezone` is still unknown, and
the gate would fail.

**2a. Ask whether a printer is set up on their Mac.** Copy the locked
line. Send only this, then stop — do not probe Latch yet.

Portuguese:

> 🖨️ Tem uma impressora no seu Mac? (sim / não)

English:

> 🖨️ Is there a printer on your Mac? (yes / no)

**2b. On their next message**, whatever they answered, **probe once
through Latch before recording `printer.configured`** — the same
discipline ld-setup applies to the Pi bring-up; a yes/no alone is a
configured printer that fails on every nightly run. First tool call of
this step is `chat_status.py --busy --new-wave`. After every pending poll, a bare `--busy`
again. Do not type a progress line.

Latch's `plow_run_command` schema requires **`argv`** and runs the array
directly — no shell, no `~`. Its optional keys (`goal`, `network`, `cwd`,
`read_paths`, `write_paths`, `apple_events`, `wait_ms`, …) are fine;
`additionalProperties: false` rejects anything else, so the relay errors
and the Mac never sees `lpstat`. OpenClaw names the tool
`plow__plow_run_command` (MCP server `plow`, then the Latch tool name). **Never send `"command"`.**

**This call needs `"network": true`.** `lpstat` reaches `cupsd` over a
local Unix domain socket, and Latch's sandbox grants socket access only
when `network` is true — the flag covers **local IPC**, not just remote
access. Without it libcups reports "Bad file descriptor" rather than a real
"no destinations" answer, every time.

Exact call:

```json
{
  "argv": ["lpstat", "-p"],
  "network": true,
  "goal": "List CUPS printers on the owner's Mac for memo setup"
}
```

If the result is `{"status":"pending","handle":…}`, poll
`plow_get_result` with that handle until `ready` (Latch's call budget is
10s, not a failed Mac). `denied` / `blocked` is the owner tapping No on
the Latch card, not an unreachable device.

**`network: true` is necessary but NOT sufficient.** `cupsd` is launched
on demand by launchd, and a *sandboxed* `lpstat` cannot trigger the launchd
rendezvous that starts it: with `cupsd` idle the sandboxed call returns
"Bad file descriptor" and leaves it asleep.

So if the call above comes back `exit_code` non-zero with an
error-shaped output (`"Bad file descriptor"`, or anything that is not a
destinations list or "No destinations added."), **retry once through
`plow_run_applescript`** — a different tool, which really does run
outside the sandbox:

```json
{"app": "System Events", "script": "do shell script \"lpstat -p\"", "goal": "Wake cupsd and list CUPS printers for memo setup (sandboxed probe failed)"}
```

Take its answer as the probe's answer. It also wakes `cupsd`, so later
sandboxed runs start working on their own.

**Do not** try this as `{"argv": ["osascript", "-e", "do shell script
…"]}` through `plow_run_command`: every argv handed to that tool runs under
the sandbox, `osascript` included, and reproduces the identical error. The
unsandboxed path is the `plow_run_applescript` *tool*.

A real "No destinations added." (or a genuine list) is a real answer.
Latch parked or unreachable is also an answer, not a reason to skip
2a — you already asked it; now record the probe's outcome:

- lpstat lists a printer:

      record_setup.py /var/lib/plow/pt/config.json printer.configured=true "printer.name=<exact CUPS name>"

  as a bare invocation, two space-separated arguments. Use exactly what
  `lpstat` printed, not the display name (macOS turns `.`/spaces into `_`
  in the queue name: "virtual-printer.online" in System Settings is
  `virtual_printer_online`). Only the *key* is split on dots, so the
  value is taken verbatim, whatever's in it; quote it only if it has a
  space. **Do not wrap this in** an interpreter or a heredoc (SOUL.md).
- lpstat's own output says there are none (e.g. "No destinations
  added."), Latch is parked, or the Mac is unreachable:

      record_setup.py /var/lib/plow/pt/config.json printer.configured=false

  and say, in the owner's own language, that the memo still arrives in chat; printing
  joins automatically if a printer shows up later (that is the
  changing-one-setting path, plus a re-probe).
- the call returned an error that isn't a real lpstat report — e.g.
  `exit_code` non-zero with output like "Bad file descriptor" rather
  than an actual destinations list or "No destinations added.": still

      record_setup.py /var/lib/plow/pt/config.json printer.configured=false

  (never guess `true` without a real listing), but say plainly, in
  their language, that the printer check itself didn't run cleanly —
  not "no printer was found." Those are different claims; only make
  the one that's actually true. Printing can still be turned on later
  once the check works.

Send only the `NEXT_QUESTION` it prints (question 3a), then stop.

**3a. Ask whether the Mac stays awake at night.** There is no Latch read for
Latch's **Keep Mac Awake** switch, so the owner confirms it. Say why in the
same line: the memo reads their Mac all night, and a Mac asleep at the start
hour means no memo that night. Copy the locked line, then stop.

Portuguese:

> 💤 Eu leio seu Mac a noite toda. No Latch, o "Keep Mac Awake" está ligado? Se o Mac dormir, não sai memo. (sim / não)

English:

> 💤 I read your Mac all night. Is "Keep Mac Awake" on in Latch? If the Mac sleeps, there's no memo that night. (yes / no)

**3b. On their next message**, record what they said — a "no" or "not sure" is an
answer, not a reason to stop setup:

    record_setup.py /var/lib/plow/pt/config.json mac.awake=<true|false>

On `false`, say in one line, in the owner's own language, where the switch is (Latch's
menu, **Keep Mac Awake**; it holds the Mac awake only on power) and that the
memo still runs on any night the Mac is awake. Send only the `NEXT_QUESTION`
it prints — `close` — and move straight into the close step below (this one has
no separate question to send; "close" means do the close work now).

## Close: location, then config

**The moment `NEXT_QUESTION` says `close`, do only the three numbered
steps below — nothing else.** Do not open other skills (the daily run
loads them itself). Ask the owner for a city only as step 1 says — not
through any other tool, never before step 1 has failed or found no Mac.

Do not write `pt/config.json` until `NEXT_QUESTION` says `close`:

1. **Read location through Latch's browser** — a bare `chat_status.py --busy`
   first (the wait this follows already got its hang-on), and again after every `goto`. `plow_browser_open` scoped to
   `["ipapi.co", "ipwho.is", "ifconfig.co"]` — through the browser, never
   `plow_run_command`, whose sandbox blocks `/usr/bin/python3` (loading
   `xcrun`'s own dylib) and a `curl` fallback's DNS (`Could not resolve host`).
   `plow_browser` `action: "goto"`, `url: "https://ipapi.co/json/"`; if
   `goto` itself errors (DNS failure such as `NS_ERROR_UNKNOWN_HOST`,
   timeout, connection refused), **never retry ipapi** — `goto`
   `https://ipwho.is/` instead, and if that also errors,
   `https://ifconfig.co/json`. Stop after these three; an empty or
   malformed body is a real "can't determine" answer, not a reason to try
   the next. `plow_browser` `action: "text"` reads the JSON back; the IANA
   zone is `time_zone` / `timezone`. Then `plow_browser_close`.

   **Location not read, for any reason** — no Mac, the browser or Latch
   unavailable, no provider loads, or none gives a usable IANA timezone: ask
   the owner once, in their language, which city or time zone they are in,
   then stop. On their answer, use that place's IANA zone in step 2. Never
   invent a zone, and never answer that the memo can't be scheduled.
2. **Write** `/var/lib/plow/pt/config.json` — with this exact bare
   invocation, never by composing the JSON yourself, never with the write tool:

       /opt/plow/skills/memo-setup/scripts/finalize_setup.py /var/lib/plow/pt/config.json --owner-tz <IANA zone from step 1>

   It reads the draft, stores the start hour as the owner named it (in their
   own zone; the scheduler fires the job in that zone) with the default
   four-hour window and $100 ceiling, validates against the gate **before**
   anything lands, and prints `CONFIG:written` plus the start line. It then
   queues the one-off first read of their company (`queued: memo-bootstrap`, or
   `already queued:` on a re-run) a minute out. On failure it prints why and
   writes nothing: an unfinished interview, an unknown zone, or a gate
   failure. That refusal is the answer — do not hand-write the file
   around it.

   If you want to re-check afterwards, the gate is:

       /opt/plow/skills/memo-shared/scripts/pt_config_gate.py /var/lib/plow/pt/config.json

   **Paste the gate's output verbatim.** Empty output is pass. Then run
   `/opt/plow/skills/memo-schedule/scripts/register_crons.py` and
   paste its output. Finally clear the draft — **with this exact bare
   invocation, never a `rm`, never an interpreter, never `os.remove`**:

       record_setup.py /var/lib/plow/pt/config.json --done

   It prints `DRAFT:cleared`. It is idempotent, and it refuses if the
   interview is somehow unfinished (it names what is missing) — that
   refusal is information, not something to work around.

Say the result in CHAT_VOICE, using the hour they named, never the
container's zone or `TZ`. Portuguese:

> 📰 Pronto — começo toda noite à 1h, e já estou lendo pra te dizer o que acho que é a sua empresa.

English:

> 📰 All set — I start every night at 1:00, and I'm reading now to tell you what I think your company is.

Swap in the hour they chose.
