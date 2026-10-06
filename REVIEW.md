# Review instructions — the-founder-memo-openclaw-agent

Repo-specific reviewer policy. The universal voice posture (Broken-Glass,
pro-simplification, and the don't-propose list) is supplied by the reviewers
themselves and is deliberately not restated here.

## What this repo is

**One agent**: The Founder Memo on OpenClaw. Every night, from a configured
hour, it spends up to a window and a dollar ceiling reading the founder's mail,
messages, meetings, calendar and web through Latch, runs an adversarial
tournament in the voice of advisors the founder trusts, and prints the top three
priorities on the founder's Mac, with the same PDF in chat. It began as a fork of
The Founder Times (the morning paper); the newspaper desks are gone. This repo is
the prompt, the `memo-*` skills and their scripts, a plugin, and its own `boot/`,
built directly on the upstream OpenClaw image rather than on
`plow-pbc/plow-openclaw-agent`. `README.md` owns
the product prose and this file does not repeat it. Flag drift between that
prose and the code, in either direction.

**Operating point:** pre-PMF, a handful of installs, each one owner's agent
running in Docker against their own Plow line. One owner, one container: there is no shared state between owners, no
cross-owner concurrency and no scale to design for. So the dominant lens is
**YAGNI**. Decline remedies that add retries, fallbacks, caches, multi-tenant
or cross-owner guards, or abstractions for a second caller that does not
exist; prefer the deletion or the inline version. One owner's own runs can
overlap (the nightly run, a `--now` run, the bootstrap), so the lock that
guards that is real; keep it. A finding must name what breaks for one owner
today. A reliability guess about load this repo will not see is at most
`[low]`.

**Security findings name a reachable loss.** The owner trusts their own
agent. "A prompt-injected or misbehaving agent could do X with the owner's
own data" is not blocking unless X reaches another person, spends money, or
moves the owner's data out of their Mac and chat. Before labeling a finding
`[blocking] security`, state the concrete loss if it fired today; without one
it is at most `[low]`, worded as a question. Do not prescribe sandboxes,
allowlists or validation layers for threats this operating point does not
face.

**The one carve-out is the owner's data.** The agent holds that owner's
credential and reaches their mail, calendar, browser and printer through
Latch, so a credential, a chat id, an account name or private personal data
anywhere in the tracked tree is blocking. That includes the edition renders
under `index/`: their owner data is synthetic, and the public, sourced
advisor quotes in them are intended.

Skills, prompts and comments are in English. The memo is written in the
owner's language, which `memo-intake` records. Owner-facing text that hard-codes
a language around that is a finding.

## Review priority

Subtractive remedies outrank additive ones. Three gates here can be checked
directly, and they come ahead of anything else:

- **It reports. It does not act, and it does not invent.** The memo makes no
  purchases, bookings, logins or downloads, and every claim carries an item that
  re-opens. Block a change that lets a skill act on what it reads, or that turns
  a failed read into content ("no reply", "none found", a cost of $0.00). A
  failed read reaches the page as a failure; an unknown cost prints as unknown.
- **The money bound is real.** The night's spend is priced from the models the
  install configured (`MEMO_MODEL_*_PRICE`), and a generation starts only when
  `run_cost.py can-start` and the window both allow it. Block a change that
  lets a role model run unpriced, puts the critic on the writer's provider, or
  names a model inside skill text instead of config.
- **One writer per page.** Entity pages change only through `entity_page.py`,
  which keeps the owner's own edits; the run page, Q&A and resources are
  rewritten whole after a fresh read. Block a hand-written merge.
- **Pins are the supply chain.** The OpenClaw `FROM` carries a digest. The
  Agent Index client is fetched by commit sha and checked by sha256. uv,
  agentsview, WeasyPrint, pydyf and PyYAML are exact versions. Block a move
  to a mutable ref. Bumping a pin to a new immutable revision is ordinary
  work, not a finding.
- **`boot/` does not grow a second base.** Identity, the MCP bridge, the
  Agent Index reporter and the model wiring are what `plow-openclaw-agent`
  provides to every other OpenClaw variant. A fix there belongs in the base
  first. New boot logic the base already has is a finding, and the remedy is
  to delete it, not to keep both in sync.

**Repo-specific contrast pairs:**

| Variant DON'T (suppress / flag-as-shape) | Variant DO (real finding) |
|---|---|
| Flag a default, an advisor or a source for being **specific to one founder's memo**. Being one person's advisor is the reason this repo exists. Generality here is bloat, not a fix. | Flag a change that a **sibling repo owns**. Research, mail, calendar and print go through Latch's tools and the gog grammar. The memo's wiki pages and the shared entity pages follow `plow-wiki`'s schema and CLI. The usage reporter is `agent-index-client`, which this repo only pins. Account, login, mint and revoke belong to `plow-agents`. The test: who else would have to change if this fact changed? |

**Update cadence:** edit this when the operating point moves. Product and architecture
edits belong in `README.md`, not here.
