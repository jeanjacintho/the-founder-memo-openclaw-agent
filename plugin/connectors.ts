// Google and Slack through the Plow API, for an install with no Latch (no Mac).
// The owner's provider tokens stay in Plow: the agent sends argv to
// POST /v1/connectors/{google,slack}/run and gets the command's output back.
// Files cross that boundary as base64, so the plugin turns them into and out of
// the agent's workspace and the model only ever sees paths.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, join, resolve } from "node:path";
import { wrapExternalContent } from "openclaw/plugin-sdk/security-runtime";
import type { Account } from "./transport.ts";

export type Provider = "google" | "slack";
export const WORKSPACE = "/var/lib/plow/workspace";

// Latch is present when the owner's Mac answers `plow_device_status` through the
// relay right now. Every agent has a relay URL, Mac or not, so only an answer
// says there is a Mac. Checked per turn and per call, cached briefly: a Plow
// restart or a sleeping Mac comes and goes within minutes.
const LATCH_TTL_MS = 30_000;
const shared = globalThis as typeof globalThis & { plowLatchProbe?: { at: number; present: Promise<boolean> } };

function mcpMessage(contentType: string, text: string): Record<string, unknown> | undefined {
  const parse = (chunk: string) => { try { return JSON.parse(chunk) as Record<string, unknown>; } catch { return undefined; } };
  if (!contentType.includes("text/event-stream")) return parse(text);
  for (const line of text.split("\n")) {
    const message = line.startsWith("data:") ? parse(line.slice(5).trim()) : undefined;
    if (message && ("result" in message || "error" in message)) return message;
  }
  return undefined;
}

async function probeLatch(): Promise<boolean> {
  const url = process.env.PLOW_MCP_URL;
  const token = process.env.PLOW_AGENT_TOKEN;
  if (!url || !token) return false;
  try {
    const response = await fetch(url, {
      method: "POST", redirect: "error", signal: AbortSignal.timeout(10_000),
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", Accept: "application/json, text/event-stream" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "plow_device_status", arguments: {} } }),
    });
    if (!response.ok) return false;
    const message = mcpMessage(response.headers.get("content-type") ?? "", await response.text());
    return Boolean(message && "result" in message);
  } catch {
    return false;
  }
}

export function latchPresent(now = Date.now()): Promise<boolean> {
  const cached = shared.plowLatchProbe;
  if (cached && now - cached.at < LATCH_TTL_MS) return cached.present;
  const present = probeLatch();
  shared.plowLatchProbe = { at: now, present };
  return present;
}

export function forgetLatchProbe(): void {
  delete shared.plowLatchProbe;
}

const LATCH_ANSWERS = "Your owner's Mac (Latch) is connected: reach Google through it as the skills describe (plow-gog via plow_run_command). plow_google and plow_connect for Google are for when the Mac is not connected; Slack always goes through plow_slack.";

/** The connector note for one turn, from this turn's probe: only when the Mac does not answer, so a Latch turn reads as before. */
export async function latchContext(): Promise<string | undefined> {
  return await latchPresent() ? undefined
    : "Your owner's Mac (Latch) is not connected right now: use plow_google for Gmail and Calendar (plow_slack for Slack, as always), and plow_connect if an account is not connected yet.";
}
// Plow's plow-gog runner gives up at 60s; leave room for minting and the network.
const RUN_TIMEOUT_MS = 90_000;

export type Answer = { ok: true; payload: Record<string, unknown> } | { ok: false; status: number; detail: string };

async function post(account: Pick<Account, "apiBase">, path: string, body: unknown): Promise<Answer> {
  const token = process.env.PLOW_AGENT_TOKEN;
  if (!token) throw new Error("PLOW_AGENT_TOKEN is required");
  const response = await fetch(`${account.apiBase}/v1${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(RUN_TIMEOUT_MS),
  });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (response.ok) return { ok: true, payload };
  // Plow's refusals name the rule and never quote the caller, so they pass through as-is.
  const detail = typeof payload.detail === "string" ? payload.detail : `Plow answered HTTP ${response.status}`;
  return { ok: false, status: response.status, detail };
}

/**
 * Local files an argv names for gog to read (`--attach a,b` and `--*-file`),
 * the same rule Plow's runner applies. Each is read here, sent as base64, and
 * named in argv as `@N` instead.
 */
export async function withUploads(argv: readonly string[], workspace = WORKSPACE): Promise<{ argv: string[]; files: { name: string; content_base64: string }[] }> {
  const out = [...argv];
  const files: { name: string; content_base64: string }[] = [];
  const upload = async (path: string) => {
    files.push({ name: basename(path), content_base64: (await readFile(resolve(workspace, path))).toString("base64") });
    return `@${files.length - 1}`;
  };
  for (let i = 0; i < out.length; i++) {
    const arg = out[i]!;
    if (arg === "--") break;
    if (!arg.startsWith("--")) continue;
    const eq = arg.indexOf("=");
    const flag = eq === -1 ? arg : arg.slice(0, eq);
    if (flag !== "--attach" && !flag.endsWith("-file")) continue;
    const at = eq === -1 ? i + 1 : i;
    const value = eq === -1 ? out[at] : arg.slice(eq + 1);
    if (value === undefined || value === "" || value === "-") continue;
    const paths = flag === "--attach" ? value.split(",").filter(Boolean) : [value];
    const refs = [];
    for (const path of paths) refs.push(await upload(path));
    out[at] = `${eq === -1 ? "" : `${flag}=`}${refs.join(",")}`;
    if (eq === -1) i++;
  }
  return { argv: out, files };
}

/**
 * The command words plow-gog plans from: its own account flag and
 * `--confirm-conflict` may come anywhere and are not part of the command. The
 * account spellings are exactly the planner's (`plowGog.ts` `accountAt`):
 * `--account x`, `-a x`, `--account=x`, `-a=x` and the attached `-ax`.
 */
export function commandWords(argv: readonly string[]): string[] {
  const words: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;
    if (arg === "--account" || arg === "-a") i++;
    else if (arg.startsWith("--account=") || arg.startsWith("-a") || arg === "--confirm-conflict") continue;
    else words.push(arg);
  }
  return words;
}

const safe = (name: string) => basename(name).replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120) || "file";

/**
 * `gmail attachment` comes back base64 inside the output. It is written to the
 * workspace, and the model sees only where it went: the bytes never enter the
 * conversation.
 */
export async function savingAttachment(argv: readonly string[], output: string, workspace = WORKSPACE): Promise<string> {
  const words = commandWords(argv);
  if (!["gmail", "mail", "email"].includes(words[0] ?? "") || words[1] !== "attachment") return output;
  let answer: { stdout?: unknown };
  let file: { filename?: unknown; mimeType?: unknown; bytes?: unknown; contentBase64?: unknown };
  try {
    answer = JSON.parse(output);
    file = JSON.parse(String(answer.stdout));
  } catch {
    return output;
  }
  if (typeof file.contentBase64 !== "string") return output;
  const dir = join(workspace, "attachments");
  await mkdir(dir, { recursive: true });
  const savedTo = join(dir, `${safe(words[2] ?? "message")}_${safe(String(file.filename ?? "attachment"))}`);
  const content = Buffer.from(file.contentBase64, "base64");
  await writeFile(savedTo, content, { mode: 0o600 });
  return JSON.stringify({ ...answer, stdout: { saved_to: savedTo, filename: file.filename, mimeType: file.mimeType, bytes: content.length } });
}

export type ToolText = { isError?: true; content: { type: "text"; text: string }[]; details: Record<string, unknown> };

const untrusted = (provider: Provider, text: string) => wrapExternalContent(text, { source: "api", sender: provider === "google" ? "Google" : "Slack" });

/** While Latch answers, Google stays on the Mac exactly as before. Latch has no Slack, so Slack always goes through Plow. */
async function latchRefusal(provider: Provider): Promise<ToolText | undefined> {
  return provider === "google" && await latchPresent() ? { isError: true, content: [{ type: "text", text: LATCH_ANSWERS }], details: { latch: true } } : undefined;
}

/** One `plow_google` / `plow_slack` call, as the tool returns it. */
export async function runConnector(account: Pick<Account, "apiBase">, provider: Provider, argv: string[], timezone?: string, workspace = WORKSPACE): Promise<ToolText> {
  const latch = await latchRefusal(provider);
  if (latch) return latch;
  let body: Record<string, unknown> = { argv };
  if (provider === "google") {
    let upload;
    try { upload = await withUploads(argv, workspace); }
    catch (error) {
      return { isError: true, content: [{ type: "text", text: `Could not read a file named in argv: ${(error as NodeJS.ErrnoException).code ?? "read failed"}` }], details: {} };
    }
    body = { argv: upload.argv, ...(upload.files.length ? { files: upload.files } : {}), ...(timezone ? { timezone } : {}) };
  }
  const result = await post(account, `/connectors/${provider}/run`, body);
  if (!result.ok) return { isError: true, content: [{ type: "text", text: result.detail }], details: { status: result.status } };
  const raw = typeof result.payload.output === "string" ? result.payload.output : "";
  const output = provider === "google" ? await savingAttachment(argv, raw, workspace) : raw;
  return { content: [{ type: "text", text: untrusted(provider, output) }], details: {} };
}

/**
 * `plow_connect`: the link the owner opens to connect, which the agent sends
 * them in chat. Plow builds it on its browser-facing address, so it is used as
 * given; the code inside it is single-use and lasts minutes, not seconds.
 */
export async function connectLink(account: Pick<Account, "apiBase">, provider: Provider): Promise<ToolText> {
  const latch = await latchRefusal(provider);
  if (latch) return latch;
  const path = `/connectors/${provider === "google" ? "gmail" : "slack"}/connect-code`;
  const result = await post(account, path, {});
  if (!result.ok) return { isError: true, content: [{ type: "text", text: result.detail }], details: { status: result.status } };
  const url = result.payload.url;
  if (typeof url !== "string") return { isError: true, content: [{ type: "text", text: "Plow returned no connect link." }], details: {} };
  return { content: [{ type: "text", text: JSON.stringify({ url, expires_at: result.payload.expires_at }) }], details: { url } };
}

/** Said to the owner's session when Plow reports its connectors changed. */
const SLACK_CHANGED = "Plow says your owner's connections just changed. Re-check Slack (plow_slack [\"status\"]) and carry on with anything that was waiting on it; Google stays on the Mac.";

export const CONNECTORS_CHANGED = "Plow says your owner's Google or Slack connections just changed. Re-check them (plow_google [\"accounts\"], plow_slack [\"status\"]) and carry on with anything that was waiting on a connection.";

type SystemEvents = {
  enqueueSystemEvent: (text: string, options: { sessionKey: string; contextKey?: string; replace?: boolean }) => boolean;
  requestHeartbeat: (options: { source: "notifications-event"; intent: "immediate"; reason: "wake"; agentId: string; sessionKey: string }) => void;
};

/** On `connectors.changed`, tell the owner's session and wake it to re-check: Slack always, Google only when it is not on the Mac. */
export async function onConnectorsChanged(system: SystemEvents, sessionKey: string): Promise<void> {
  forgetLatchProbe();
  const notice = await latchPresent() ? SLACK_CHANGED : CONNECTORS_CHANGED;
  // One pending notice at a time: a burst of changes is still one re-check.
  system.enqueueSystemEvent(notice, { sessionKey, contextKey: "plow:connectors.changed", replace: true });
  // A targeted, unscheduled wake: OpenClaw runs it now for this session only when
  // it is exactly this shape (source notifications-event, intent immediate,
  // reason "wake", a session and a configured agent; heartbeat-wake-policy
  // isTargetedUnscheduledWake). Any other shape is an ordinary heartbeat wake,
  // which waits on the heartbeat schedule: the first event after boot ran, the
  // rest were skipped as not due.
  system.requestHeartbeat({ source: "notifications-event", intent: "immediate", reason: "wake", agentId: "main", sessionKey });
}
