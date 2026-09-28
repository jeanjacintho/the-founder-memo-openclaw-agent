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

/** Alert the owner once when a paper cron ends with a runtime failure. */
export async function notifyFailedPaperRun(event: AgentEnd, context: AgentContext): Promise<void> {
  const runId = event.runId;
  const jobId = context.jobId;
  if (event.success || deliveryWasConfirmed(event.messages) || !runId || !jobId || !paperJob.test(jobId)) return;
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
