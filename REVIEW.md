# Review instructions — the-founder-times-openclaw-agent

Repo-specific reviewer policy. The universal voice posture (Broken-Glass,
pro-simplification, and the don't-propose list) is supplied by the reviewers
themselves and is deliberately not restated here.

## What this repo is

**One agent**: The Founder Times on OpenClaw. It is a morning paper
researched on the owner's Mac and printed there, or sent as a PDF in chat. It
is the OpenClaw port of `jeanjacintho/the-plow-times-hermes-agent`, the same
paper on Hermes. This repo is the prompt, the `pt-*` skills and their
scripts, a plugin, and its own `boot/`, built directly on the upstream
OpenClaw image rather than on `plow-pbc/plow-openclaw-agent`. `README.md` owns
the product prose and this file does not repeat it. Flag drift between that
prose and the code, in either direction.

**Stage:** pre-PMF, early. A handful of installs, each one owner's paper
running in Docker against their own Plow line. The agent holds that owner's
credential and reaches their mail, calendar, browser and printer through
Latch, so a credential, a chat id, an account name or private personal data
anywhere in the tracked tree is blocking. That includes the edition renders
under `index/`, which are drawn from synthetic data.

Skills, prompts and comments are in English. The paper is written in the
owner's language, which `pt-intake` records. Owner-facing text that hard-codes
a language around that is a finding.

## Review priority

Subtractive remedies outrank additive ones. Three gates here can be checked
directly, and they come ahead of anything else:

- **It reports. It does not act, and it does not invent.** The paper makes no
  purchases, bookings, logins or downloads, and every claim carries a source.
  Block a change that lets a skill act on what it reads, or that turns a
  failed read into content (an empty agenda, a clear inbox, a paragraph with
  no page behind it). A failed read has to reach the page as a failure.
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
| Flag a section, a default, the advisor's desk or its sources for being **specific to one owner's paper**. Being one person's paper is the reason this repo exists. Generality here is bloat, not a fix. | Flag a change that a **sibling repo owns**. Research, mail, calendar and print go through Latch's tools and the gog grammar. The paper's wiki pages follow `plow-wiki`'s schema and CLI. The usage reporter is `agent-index-client`, which this repo only pins. Account, login, mint and revoke belong to `plow-agents`. The test: who else would have to change if this fact changed? |

**Update cadence:** edit this when the stage changes. Product and architecture
edits belong in `README.md`, not here.
