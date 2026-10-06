import { request } from "./transport.ts";
import { editionFailedNotice } from "./owner-phrases.ts";

type AgentEnd = { runId?: string; success: boolean; messages?: unknown[] };
type AgentContext = { jobId?: string; sessionKey?: string; sessionId?: string };

const notifiedRuns = new Set<string>();
const paperJob = /^memo-(?:nightly|now)$/;
const paperMarker = "[PLOW_PAPER_RUN]";

function textValues(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(textValues);
  if (value === null || typeof value !== "object") return [];
  return Object.values(value as Record<string, unknown>).flatMap(textValues);
}

/**
 * OpenClaw 2026.9.6 agent_end context has jobId (the UUID), not jobName.
 * The cron runner includes both in the initial message envelope:
 * `[cron:<jobId> <jobName>] ...`.
 */
function cronJobName(jobId: string | undefined, messages: unknown[] | undefined): string | undefined {
  for (const message of messages ?? []) {
    if (message === null || typeof message !== "object") continue;
    const record = message as Record<string, unknown>;
    const nestedMessage = record.message as Record<string, unknown> | undefined;
    const role = record.role ?? nestedMessage?.role;
    if (role !== "user") continue;
    for (const text of textValues(record.content ?? nestedMessage?.content)) {
      const match = /\[cron:([^\s\]]+)\s+([^\s\]]+)\]/.exec(text);
      if (match && (!jobId || match[1] === jobId)) return match[2];
    }
  }
  return undefined;
}

function isPaperRun(messages: unknown[] | undefined, context: AgentContext): boolean {
  if (!context.jobId && !context.sessionKey?.includes(":cron:")) return false;
  const name = cronJobName(context.jobId, messages);
  if (name && paperJob.test(name)) return true;
  return (messages ?? []).some(message => {
    if (message === null || typeof message !== "object") return false;
    const record = message as Record<string, unknown>;
    const nested = record.message as Record<string, unknown> | undefined;
    if ((record.role ?? nested?.role) !== "user") return false;
    return textValues(record.content ?? nested?.content).some(text => text.includes(paperMarker));
  });
}

function deliveryWasConfirmed(messages: unknown[] | undefined): boolean {
  // post_to_chat.py emits this only after the chat POST succeeds. Finalizer
  // failures must not be described to the owner as an undelivered edition.
  return (messages ?? []).some(message => {
    const content = JSON.stringify(message);
    return content.includes("chat edition posted (") ||
      /held for \d\d:\d\d — memo-deliver posts it/.test(content);
  });
}

function alreadyMessagedOwner(messages: unknown[] | undefined): boolean {
  const visit = (value: unknown): boolean => {
    if (Array.isArray(value)) return value.some(visit);
    if (value === null || typeof value !== "object") return false;
    const record = value as Record<string, unknown>;
    const fn = record.function && typeof record.function === "object"
      ? record.function as Record<string, unknown> : undefined;
    const name = record.name ?? record.toolName ?? fn?.name;
    const rawArgs = record.input ?? record.args ?? record.arguments ?? fn?.arguments;
    let args = rawArgs;
    if (typeof rawArgs === "string") {
      try { args = JSON.parse(rawArgs); } catch { args = undefined; }
    }
    if (name === "message" && args !== null && typeof args === "object") {
      const input = args as Record<string, unknown>;
      const target = input.to ?? input.target;
      if (input.action === "send" && target === "plow-owner" &&
        (input.channel === undefined || input.channel === "plow") &&
        (input.accountId === undefined || input.accountId === "chat")) return true;
    }
    return Object.values(record).some(visit);
  };
  return visit(messages);
}

const toolResultRole = new Set(["tool", "toolResult", "tool_result"]);

/** Ids of the assistant's tool calls that ran `run_attempts.py <subcommand>`. */
function callIds(messages: unknown[], subcommand: string): Set<string> {
  const ids = new Set<string>();
  const visit = (value: unknown) => {
    if (Array.isArray(value)) return value.forEach(visit);
    if (value === null || typeof value !== "object") return;
    const record = value as Record<string, unknown>;
    const args = record.arguments ?? record.input ?? record.args;
    if (typeof record.id === "string" && args !== undefined && JSON.stringify(args).includes(`run_attempts.py ${subcommand}`)) ids.add(record.id);
    Object.values(record).forEach(visit);
  };
  for (const message of messages) {
    const record = message as Record<string, unknown> | null;
    if (record !== null && typeof record === "object" && (record.role ?? (record.message as Record<string, unknown> | undefined)?.role) === "assistant") visit(record);
  }
  return ids;
}

// A run that stopped because the day's attempts are spent did so on purpose, and `begin` owns the
// notice: it answered `stop` (the owner is told, now or on an earlier start). A generic failure
// notice on top would repeat it. A cooldown returns the same confirmed-notice result.
// `stop-untold` means the post failed, so the generic notice still goes out.
// Only the script's own result counts: the tool result
// paired with the call that ran it, never text the model or another tool produced.
function stoppedOnPurpose(messages: unknown[] | undefined): boolean {
  const all = messages ?? [];
  const begins = callIds(all, "begin");
  if (begins.size === 0) return false;
  return all.some(message => {
    if (message === null || typeof message !== "object") return false;
    const record = message as Record<string, unknown>;
    const nested = record.message as Record<string, unknown> | undefined;
    if (!toolResultRole.has(String(record.role ?? nested?.role))) return false;
    const callId = record.toolCallId ?? record.tool_call_id ?? record.toolUseId ?? nested?.toolCallId ?? nested?.tool_call_id;
    return typeof callId === "string" && begins.has(callId) &&
      textValues(record.content ?? nested?.content).some(text => text.trim() === "stop");
  });
}

/** Alert the owner once when a paper cron ends without confirmed delivery. */
export async function notifyFailedPaperRun(event: AgentEnd, context: AgentContext): Promise<void> {
  const runId = event.runId;
  const jobId = context.jobId;
  if (
    deliveryWasConfirmed(event.messages) || alreadyMessagedOwner(event.messages) || stoppedOnPurpose(event.messages) ||
    !isPaperRun(event.messages, context) || !runId
  ) return;
  const key = `${jobId ?? context.sessionKey ?? context.sessionId ?? "paper"}:${runId}`;
  if (notifiedRuns.has(key)) return;
  // Claim before I/O: this hook must never send twice for one run, even when
  // Plow is unavailable and the hook is called again during shutdown.
  notifiedRuns.add(key);

  const apiBase = process.env.PLOW_API_BASE?.replace(/\/$/, "");
  const chat = process.env.PLOW_HOME_CHANNEL;
  if (!apiBase || !chat || !process.env.PLOW_AGENT_TOKEN) return;
  await request({ apiBase }, `/chats/${encodeURIComponent(chat)}/messages`, {
    body: await editionFailedNotice(), attachment_uids: [],
  });
}
