import { request } from "./transport.ts";
import { editionFailedNotice } from "./owner-phrases.ts";

type AgentEnd = { runId?: string; success: boolean; messages?: unknown[] };
type AgentContext = { jobId?: string };

const notifiedRuns = new Set<string>();
const paperJob = /^pt-(?:daily-edition(?:-now)?|paper-|subscription-|oneoff-)/;

function deliveryWasConfirmed(messages: unknown[] | undefined): boolean {
  // post_to_chat.py emits this only after the chat POST succeeds. Finalizer
  // failures must not be described to the owner as an undelivered edition.
  return (messages ?? []).some(message => JSON.stringify(message).includes("chat edition posted ("));
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

/** Alert the owner once when a paper cron ends without confirmed delivery. */
export async function notifyFailedPaperRun(event: AgentEnd, context: AgentContext): Promise<void> {
  const runId = event.runId;
  const jobId = context.jobId;
  if (deliveryWasConfirmed(event.messages) || alreadyMessagedOwner(event.messages) || !runId || !jobId || !paperJob.test(jobId)) return;
  const key = `${jobId}:${runId}`;
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
