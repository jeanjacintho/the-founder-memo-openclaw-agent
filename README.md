# The Founder Memo

Your nightly advisor, printed. While you sleep it reads your mail, messages,
meetings, calendar and the web on your Mac, argues the options out in the voice
of advisors you trust, and puts **the one priority that matters most** in
the printer tray — the same PDF in chat.

An [OpenClaw](https://github.com/openclaw/openclaw) agent on
[Plow Chat](https://howto.plow.co/). It is one founder's advisor: it starts at
the hour you name, spends up to the window and the dollar ceiling you set
(default four hours and $100 a night), and writes in the language you write.
The bar is a memo good enough to pay that for, and better informed each night
than the last.

## What it is

Every night, from the start hour, it runs a tournament on your Mac through
[Latch](https://howto.plow.co/latch):

1. **Orient** — reads its advisors, your goals and the questions it still has,
   last night's memo and the signals you let it hear, places your company on
   each advisor's stage map, and picks the people, companies and deals that
   matter now.
2. **Gather** — one investigator per name, through every source your Mac has
   (Gmail and calendar, iMessage, WhatsApp, contacts, meeting transcripts in
   msgvault when installed, the web and the dashboards you name), and a check
   on whether last night's first steps happened.
3. **Generations** — writers propose, two critics per proposal prosecute it
   (one on the facts, one on the strategy, on a different model from a
   different provider), a culler keeps the three best. At least three
   generations, then more while the window and the ceiling allow.
4. **Freshness** — re-reads the names the winners rest on.
5. **Publish** — prints the memo: the culler's #1 priority with its evidence,
   its **first step** and a sourced line from the advisor it applies (a 72 mm
   receipt printer, `printer.paper: "72mm"`, gets that card alone); the questions
   whose answers would change the advice; and one line with what tonight's
   research cost and how long it took ("cost unavailable" when a model has no
   price — never $0.00).

The advisors are Patrick Salyer (enterprise go-to-market), Paul Graham (the
first users and product, growth, fundraising) and Ben Horowitz (the CEO's job,
executives, crises), each a file of their published thinking with every
quotable line sourced from a public page.

You do not fill a profile. Setup asks when to start, whether there is a
printer, and whether the Mac stays awake at night. A minute later it does a
first full read of your company and texts you what it thinks your company is,
so you can correct it before the first night. Reply to any memo to correct it
or answer one of its questions.

If a source cannot be read, the memo says so — it does not invent the paragraph.
It reports. It does not act on what it finds: no purchases, no bookings, no
logins, no downloads, no messages sent on your behalf.

## What it keeps

Everything durable is your wiki at `~/Plow/wiki` (Latch's Obsidian-style wiki):
a page per person and company it investigated (`entities/people`,
`entities/orgs`, a current state and a dated timeline, each fact pointing back
at the message it came from — never an excerpt), and the memo's own pages under
`projects/founder-memo/`: each night's memo with its first steps, the questions
it has for you, the sources it may revisit, and each run's private research
state. Your edits in Obsidian win. Every night ends with a `wiki snapshot`, so
each night is a diff you can read or revert.

An install upgraded from The Founder Times keeps its research start (its old
delivery hour minus its lead, clamped at midnight), printer, signals and advisor
opt-out; an opt-out disables the nightly memo until you turn it on in chat.

## Install (local)

You need Git, Docker Compose, and [plow-agents](https://github.com/plow-pbc/plow-agents).

```sh
git clone https://github.com/jeanjacintho/the-founder-memo-openclaw-agent.git
cd the-founder-memo-openclaw-agent

plow-agents login                 # text the printed code
plow-agents lines                 # pick a free line
plow-agents mint LINE_UID         # writes ./plow-credentials before the first up
docker compose up --build -d
docker compose logs -f agent      # wait for: plow-boot: identity resolved … and [gateway] ready
```

Text the line you minted. The first message is the memo's start hour, not a
profile interview.

```sh
docker compose down          # stop, keep the memo's state, sessions and schedule
docker compose down -v       # wipe the state volume (fresh setup)
plow-agents revoke           # retire the line in plow-credentials
```

`plow-credentials` is gitignored. Do not commit it.

## Deploy (cloud)

Build and push the image to a registry you control that Plow can pull, then
deploy it by digest:

```sh
plow-agents image build REGISTRY/REPOSITORY:TAG
plow-agents image push REGISTRY/REPOSITORY:TAG
plow-agents deploy REGISTRY/REPOSITORY@sha256:DIGEST --line LINE_UID
```

A cloud host injects the credentials; there is no `plow-credentials` file.
The image lists itself on the [Agent Index](https://aiworthusing.com/agent-index)
as `thefoundertimes` (`AGENT_ID`, `AGENT_NAME`, `AGENT_BLURB` in the Dockerfile)
and reports its token usage through the base's pinned reporter.

## Your Mac: Latch, the printer and the wiki

Run [Latch](https://howto.plow.co/latch) on the Mac this agent should drive,
signed in to the same Plow account. The agent reaches it with its own
credential — nothing to paste, no restart. Chat works without Latch; research,
the printer and the wiki do not. Turn on Latch's **Keep Mac Awake**: a Mac
asleep through the whole window means no memo that night (you get one line
saying so), and a print that cannot reach the printer is reported in chat in
your language.

The printer is whatever CUPS on the Mac calls it (`lpstat -p`); setup asks
once. The wiki is `~/Plow/wiki/projects/founder-memo/`.

## How it runs

- **Chat.** The owner's phone DM is the agent's main session. Before each of
  the owner's turns the Plow channel runs the setup gate and hands the model
  its answer once; the model uses that result for the rest of the turn.
  Heartbeats, scheduled jobs, groups and sub-agents skip setup.
  Replies appear automatically in the current conversation;
  groups are only listened to for priority signals and never get replies or
  setup questions. Non-owner messages in untrusted DMs and non-owner email
  turns get no tools. Only the owner's main phone DM can start a new group.
- **Recovery.** Chat and email messages interrupted before OpenClaw adopts
  them remain available after restart. Later messages already handled are
  skipped while the earlier source is recovered. Once OpenClaw adopts a
  source, the runtime owns its remaining work.
- **Schedule.** `memo-nightly` is an OpenClaw scheduler job (`openclaw cron`)
  at `memo.start` in **your** timezone, registered by
  `memo-schedule/scripts/register_crons.py`: an isolated turn on the chat's own
  model with a budget of the window plus an hour, no automatic delivery — the
  memo posts itself as a PDF. "Run it now" in chat queues the same job as a
  one-shot. Jobs live in the state volume and survive restarts and
  `docker compose up --build`; on a fresh volume, setup (or any schedule change
  in chat) registers them again. After updating the image of an existing
  install, register again so they pick up its prompt:
  `docker compose exec agent bash -l -c /opt/plow/skills/memo-schedule/scripts/register_crons.py`.
- **Engine.** The night is a thin conductor that spawns one coordinator per
  phase, which spawns its own investigators, writers, critics and culler
  (two levels deep, at most ten at a time), so its context stays flat however
  many generations run.
- **Idle turns.** Main-session heartbeats are disabled (`every: "0m"`).
  Memos run through their scheduler jobs; boot replaces an older main
  heartbeat configuration with this disabled setting.
- **Scripts.** The `memo-*` skills' Python scripts run on Python 3.13 with
  WeasyPrint in a root-owned venv (`/opt/plow/pt-venv`). The memo's state is
  `/var/lib/plow/pt` (config, the accepted checkpoint, run scratch).

## Config

`/var/lib/plow/pt/config.json`, written by setup and changed by texting:

| Key | Default | |
|---|---|---|
| `memo.start` | `01:00` | when the night starts, your clock |
| `memo.window_minutes` | `240` | how long it researches; the memo prints when Publish finishes |
| `memo.max_usd` | `100` | the night's dollar ceiling, checked before each generation after the third |
| `printer.configured`, `printer.name` | from setup's probe | the CUPS queue it prints to |
| `signals.group_chat`, `.email`, `.imessage` | `false` | what it may listen to for priorities |

## Model

Every install runs on Plow's GPT-6 Sol (`plow/openai/gpt-6-sol`). A
one-click install has nothing to configure and never leaves it. The memo's
research runs are long tool loops: on Luna they gave up before research, on
Sol they finish.

The owner of one install can move all of its inference (chat, sub-agents
and the nightly runs) to their own OpenAI account. In a login shell on
the agent (`docker compose exec agent bash -l`, or SSH on the VM):

```sh
plow-llm openai
```

It signs in with a device code, checks that the account offers
`gpt-6-sol` (the model an OpenAI account runs on: the long research runs
finish on Sol, and gave up on Luna), leaves a marker in the state volume,
and registers the memo's jobs again under the new model. Restart the agent to apply it. The sign-in
and the marker live in the state volume, so rebuilds and image updates keep
them. `plow-llm plow` moves back, and `plow-llm status` shows what the next
boot will choose.

Plow stays configured as the fallback, Sol first and then Luna: a spent
quota or an expired sign-in answers from Plow instead of failing, and Plow's
Luna answers if Plow cannot serve Sol. `AGENT_PROVIDER` (`plow`,
`openai`, `openrouter`) and `AGENT_MODEL` choose a provider from the
environment instead and outrank the marker; OpenAI then takes
`OPENAI_API_KEY` or the sign-in, and OpenRouter `OPENROUTER_API_KEY`. After
changing them, restart and run `plow-llm sync` to move the scheduled jobs.

The nightly tournament can run its writers and its critics on two models from
different providers. Set both, each with its USD price per million tokens
(`input,output`), in `plow-credentials`:

```sh
MEMO_MODEL_WRITER=plow/<provider>/<model>
MEMO_MODEL_WRITER_PRICE=<input>,<output>
MEMO_MODEL_CRITIC=plow/<another provider>/<model>
MEMO_MODEL_CRITIC_PRICE=<input>,<output>
```

The prices register the role models for OpenClaw's usage accounting. The
nightly conductor checks `run_cost.py` before another generation, using
`memo.max_usd` (default $100); an unknown cost stays unknown. Phase coordinators
can spawn up to ten leaf workers at depth two.
Boot refuses one without the other, a missing or
malformed price, and a critic from the writer's provider. With neither set,
every child runs on the chat's model.

The sign-in is a real credential for your account, kept in the state volume
where the agent's own tools can read it. Use it on an install only you
talk to.

## Groups, email and trust

Every phone group is listen-only, including groups the agent starts from the
owner's main DM. Every member, including the owner, gets only
`plow_record_signal`; inbound group turns never receive replies. Owner-initiated
messages and follow-ups requested from the owner's DM can still be posted into
the group. The inherited
`PLOW_THREAD_TRUST=ask|trusted|untrusted` policy and `plow_set_thread_trust`
set the Plow trust flag, but never make a group interactive or grant Mac tools
in this memo. In an untrusted non-owner DM the sender gets replies only,
no tools. Non-owner senders carry their normalized phone number or email
address as the sender id, so one person is one sender across chats; the owner
is `plow-owner`.

An email turn's final text never reaches the sender: it goes privately to the
owner (the chat the thread was started from, else their 1:1), and mail is sent
only with `plow_send_email`. A turn on mail from anyone but the owner has no tools, so
an email cannot make the assistant send; the owner approves in their chat and
the send comes from their turn. Each outside sender in a thread runs in a session of their own, so
their mail cannot join a run the owner is in. This image does not enable OpenClaw's native
`automations` reminders; the memo's own jobs are registered by
`register_crons.py`.

Recovery pages through unread history to the saved checkpoint; a first-contact
owner DM scans back to its last answer. An uncertain send blocks later Plow
mutations in the same run. Thread creation keys use the inbound source and
normalized payload, so a new tool-call ID does not create another thread for
that request. A new run can still explicitly send again; ordinary message sends
have no API idempotency key.

## Known limitations

- If the model provider is unreachable at the start hour, OpenClaw records the
  run as skipped and tries again only the next night. Ask for it in chat ("run
  it now") once the provider answers.
- A memo delivered while the Mac is unreachable is not recorded in the wiki,
  and the next night has no "yesterday" to check its first steps against.

## Layout

- `boot/`, `plugin/`, `prompt/` — the OpenClaw base: identity, gateway config,
  Plow channel (with the setup-gate hook) and the agent prompt.
- `skills/memo-*` — setup, intake, tournament, render, print, schedule
  and the shared scripts behind them. `skills/owners-mac`,
  `skills/google-workspace` come from the base.
- `tests/*.test.ts` — boot and plugin tests (`node --test`); `tests/pt/` —
  the memo's script tests and the repo contract (`pytest`).

## Development

Tests need no Plow credentials and no network beyond fetching pinned tools.

```sh
npm ci
npm run test:py   # memo scripts: pytest on Python 3.13 via uv
npm test          # the above, then the base's tsc, node tests and offline probe in the image
```

The OpenClaw runtime is pinned to `2026.9.6` by image digest, as in the base.

## License

MIT. See [LICENSE](LICENSE).
