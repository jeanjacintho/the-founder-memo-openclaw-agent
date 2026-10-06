# Issue #75: cost investigation and closure evidence

The original October 2–4 report measured The Founder Times on OpenClaw 2026.9.6,
through Plow's Sol route: 1,745 calls, 143.2M tokens, including 113.2M cache writes.
Those counters are not a bill or proof that the local prompt prefix changed.

## What the current image changes

- #87 restricts setup to one owner-DM turn and disables periodic heartbeats,
  including migration of an older main-session heartbeat.
- The Memo cutover in #89 uses isolated phase coordinators, short child-task
  pointers and compact checkpoint results rather than keeping all research in
  the conductor. This changes the workload; it does not establish measured savings.
- #74 and the Memo scheduler set an explicit root cron timeout: the configured
  research window plus a 60-minute publication margin. #88 bounds automatic
  retries and adds cooldowns. These do not limit individual child turns.
- Research children now default to a 3,600-second runtime timeout. The tournament
  passes 3,600 for coordinators and 900 for leaves, records a failed phase's retry
  count on the run page, and stops after a second failure instead of restarting it
  until the root watchdog fires. Stops use the existing current-checkpoint or
  failure-explanation publication path; bootstrap only sends an explanation.
- Local `process` is denied. The pinned OpenClaw makes `exec` synchronous when
  `process` is unavailable, so the Mac gate, print and wiki scripts wait internally
  without model calls to poll a background process. The scripts retain their own
  bounded waits and errors. Latch's remote handles are still settled by the scripts,
  and asynchronous research still uses `sessions_spawn` / `sessions_yield`.

## Cache investigation uses the upstream implementation

The pinned OpenClaw already observes stable system-prefix, volatile suffix and
tool-definition fingerprints, per-request token counters, and cache-read drops.
Use that implementation rather than adding a second tracer or changing cache
compatibility flags on the Plow proxy without evidence of provider support.
`cacheWrite` is supplied by the route: OpenAI-compatible transports normalize
`prompt_tokens_details.cache_write_tokens` when a proxy supplies it. Its magnitude
alone does not identify a local prompt bug.

Sources, pinned to the deployed runtime version:

- [Prompt caching](https://github.com/openclaw/openclaw/blob/v2026.9.6/docs/reference/prompt-caching.md)
- [Exec and background process behavior](https://github.com/openclaw/openclaw/blob/v2026.9.6/docs/tools/exec.md)
- [Subagent timeout configuration](https://github.com/openclaw/openclaw/blob/v2026.9.6/docs/gateway/config-tools/sessions-and-subagents.md)

## Evidence needed before closing #75

Runtime changes require owner authorization; this PR modifies no installation.
On the actual installation, record the deployed revision, route, active heartbeat
and root/child timeouts. Observe one idle hour: zero periodic heartbeat model
calls and no setup gate in background turns. Explicit connector wakes differ from
periodic heartbeats; event installs keep their replies internal.

For one authorized nightly run, enable `OPENCLAW_CACHE_TRACE=1` at launch, keeping
`OPENCLAW_CACHE_TRACE_MESSAGES`, `OPENCLAW_CACHE_TRACE_PROMPT` and
`OPENCLAW_CACHE_TRACE_SYSTEM` at `0` (the image defaults). Disable tracing afterward.
Keep `logs/cache-trace.jsonl` local: it still contains session identifiers and paths.
Share only aggregates or this projection, which drops identities and request text:

```sh
jq -c 'select(.stage == "cache:result") | {ts, request: .options.requestIndex, input: .options.input, cacheRead: .options.cacheRead, cacheWrite: .options.cacheWrite, broke: .options.broke, changes: [.options.changes[]?.code]}' "$OPENCLAW_STATE_DIR/logs/cache-trace.jsonl"
```

Aggregate transcript usage for that same window: calls, input, output, cache reads
and writes, largest input-plus-cache call, and totals by conductor/coordinator/leaf.
Separate bootstrap, owner chat and connector wakes. Inspect tool names locally:
no `process.poll`, no repeated setup gate after `READY`. Do not publish messages,
arguments or file contents. Use the `cache:state` fingerprints and `cache:result`
change codes to correlate cache-read drops; stable tracked inputs point to further
route investigation, not proof of a local prefix bug. Compare configured prices
with provider billing; unknown cost stays unknown.

On a test owner, verify a child timeout, at most one phase retry after resumption,
the failure explanation or valid checkpoint, and lock release. Confirm a successful
run still prints and posts the memo. Attach the revision and aggregates to #75;
fix any evidenced local defect and repeat the same measurement, or link a concrete
upstream issue when the remaining behavior belongs to the route. Tests alone do
not close #75. The old Times and new Memo are different workloads: percentage
savings require a comparable baseline, not the original two-day total.
