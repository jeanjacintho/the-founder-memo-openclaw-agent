# The Founder Memo

Three researched priorities for your company, printed on your Mac and delivered
as the same PDF in chat, in the language you write. An
[OpenClaw](https://github.com/openclaw/openclaw) agent on [Plow Chat](https://howto.plow.co/).

## What it does

The nightly run reads your mail, messages, meetings, calendar and named web
sources through [Latch](https://howto.plow.co/latch). It gathers dossiers on the
people and companies behind your decisions, then challenges recommendations
through at least three generations with independent facts and strategy critics.
Before publishing, it checks the decisive facts again. The compact Letter memo
contains three ranked priorities, the questions that could change them, and the
run's cost and duration. Failed reads stay unknown; claims carry sources.

Setup asks when research should start (default 01:00), probes the printer, and
keeps your advisor and signal preferences. The Mac supplies your timezone.
`memo.start` controls the start, `memo.window_minutes` defaults to four hours,
and `memo.max_usd` defaults to $100. Delivery happens when research finishes.
Existing installs retain their research start (old delivery hour minus lead,
clamped at midnight), printer, signals and priority opt-out. An opt-out disables
the nightly memo until you turn it on in chat.

Your wiki at `~/Plow/wiki` holds the sourced entity pages, goals, Q&A and delivered
memos. Open it in Obsidian and edit anything. Chat is for corrections, answers and
requests to run the memo now. It reports: no purchases, bookings, logins or downloads.

## Install (local)

You need Git, Docker Compose, and [plow-agents](https://github.com/plow-pbc/plow-agents).

```sh
git clone https://github.com/jeanjacintho/the-founder-times-openclaw-agent.git
cd the-founder-times-openclaw-agent

plow-agents login                 # text the printed code
plow-agents lines                 # pick a free line
plow-agents mint LINE_UID         # writes ./plow-credentials before the first up
docker compose up --build -d
docker compose logs -f agent      # wait for: plow-boot: identity resolved … and [gateway] ready
```

Text the line you minted. Setup begins with the nightly research start hour.

```sh
docker compose down          # stop, keep the paper, sessions and schedule
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
the printer and the wiki do not. If the Mac sleeps, the paper says what it
could not source, and a print that cannot reach the printer is reported in
chat in your language.

The printer is whatever CUPS on the Mac calls it (`lpstat -p`); setup asks
once. The wiki is `~/Plow/wiki/projects/founder-memo/`.

## How it runs

- **Chat.** The owner's phone DM is the agent's main session. Before each of
  the owner's turns the Plow channel runs the setup gate and hands the model
  its answer; groups get answers, never setup questions.
- **Schedule.** Every paper is an OpenClaw scheduler job
  (`openclaw cron`), registered by `memo-schedule/scripts/register_crons.py`
  from your memo settings: an isolated turn on the chat's own model, in **your**
  timezone (`--tz`), with no automatic delivery — the paper posts itself as a
  PDF. Jobs live in the state volume and survive restarts and
  `docker compose up --build`; on a fresh volume, setup (or any schedule
  change in chat) registers them again. They also keep the prompt they were
  registered with: after updating the image of an existing install, register
  again so they pick up its changes (the model-switch command does it too):
  `docker compose exec agent bash -l -c /opt/plow/skills/memo-schedule/scripts/register_crons.py`
  (on a VM, the same in an SSH session).
- **Scripts.** The `memo-*` skills' Python scripts run on Python 3.13 with
  WeasyPrint in a root-owned venv (`/opt/plow/pt-venv`). The paper's state is
  `/var/lib/plow/pt` (config, topics, run scratch).

## Model

Every install runs on Plow's GPT-6 Sol (`plow/openai/gpt-6-sol`). A
one-click install has nothing to configure and never leaves it. The paper's
research runs are long tool loops: on Luna they gave up before research, on
Sol they finish.

The owner of one install can move all of its inference (chat, sub-agents
and the scheduled papers) to their own OpenAI account. In a login shell on
the agent (`docker compose exec agent bash -l`, or SSH on the VM):

```sh
plow-llm openai
```

It signs in with a device code, checks that the account offers
`gpt-6-sol` (the model an OpenAI account runs on: the paper's long research
runs finish on Sol, and gave up on Luna), leaves a marker in the state volume,
and registers the paper's jobs again under the new model. Restart the agent to apply it. The sign-in
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

## Known limitations

- If the model provider is unreachable at a job's time, OpenClaw records the
  run as skipped and tries again only at the job's next time: that day's paper
  does not come by itself. Ask for it in chat ("send the paper now") once the
  provider answers.
- An edition delivered while the Mac is unreachable is not recorded in the
  wiki, and the next morning's advisor has no "yesterday" for it.
- One-shot jobs can be scheduled at most ten years ahead.

## Layout

- `boot/`, `plugin/`, `prompt/` — the OpenClaw base: identity, gateway config,
  Plow channel (with the setup-gate hook) and the agent prompt.
- `skills/memo-*` — setup, intake, tournament, render, print, schedule
  and the shared scripts behind them. `skills/owners-mac`,
  `skills/google-workspace` come from the base.
- `tests/*.test.ts` — boot and plugin tests (`node --test`); `tests/pt/` —
  newspaper tests and the repo contract (`pytest`).

## Development

Tests need no Plow credentials and no network beyond fetching pinned tools.

```sh
npm ci
npm run test:py   # newspaper scripts: pytest on Python 3.13 via uv
npm test          # the above, then the base's tsc, node tests and offline probe in the image
```

The OpenClaw runtime is pinned to `2026.9.6` by image digest, as in the base.

## License

MIT. See [LICENSE](LICENSE).
