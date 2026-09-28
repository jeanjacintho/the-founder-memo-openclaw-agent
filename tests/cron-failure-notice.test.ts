import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { notifyFailedPaperRun } from "../plugin/cron-failure-notice.ts";

test("a failed paper cron sends one short owner notice, even if agent_end repeats", async t => {
  const home = await mkdtemp(join(tmpdir(), "pt-cron-notice-"));
  await writeFile(join(home, "config.json"), JSON.stringify({ owner: { language: "Português" } }));
  const previous = { PT_HOME: process.env.PT_HOME, PLOW_API_BASE: process.env.PLOW_API_BASE,
    PLOW_HOME_CHANNEL: process.env.PLOW_HOME_CHANNEL, PLOW_AGENT_TOKEN: process.env.PLOW_AGENT_TOKEN };
  process.env.PT_HOME = home;
  process.env.PLOW_API_BASE = "https://plow.example/";
  process.env.PLOW_HOME_CHANNEL = "cht_owner";
  process.env.PLOW_AGENT_TOKEN = "fixture-token";
  t.after(async () => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await rm(home, { recursive: true, force: true });
  });

  const sent: { url: string; body: string }[] = [];
  t.mock.method(globalThis, "fetch", async (url: string | URL | Request, init?: RequestInit) => {
    sent.push({ url: String(url), body: String(init?.body) });
    return Response.json({ uid: "notice" });
  });
  const event = { runId: "run-paper-failure", success: false, error: "tool failed" };
  const context = { jobId: "pt-daily-edition" };
  await notifyFailedPaperRun(event, context);
  await notifyFailedPaperRun(event, context);

  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, "https://plow.example/v1/chats/cht_owner/messages");
  assert.equal(JSON.parse(sent[0].body).body, "A edição não foi entregue porque uma etapa necessária da execução falhou.");
});

test("successful, non-paper and already-posted runs do not send failure notices", async t => {
  t.mock.method(globalThis, "fetch", async () => { throw new Error("must not send"); });
  await notifyFailedPaperRun({ runId: "run-paper-ok", success: true }, { jobId: "pt-daily-edition" });
  await notifyFailedPaperRun({ runId: "run-heartbeat", success: false }, { jobId: "heartbeat-main" });
  await notifyFailedPaperRun({ runId: "run-posted", success: false, messages: [{
    role: "tool_result", content: [{ type: "text", text: "chat edition posted (pdf) /var/lib/plow/pt/run/paper.pdf" }],
  }] }, { jobId: "pt-daily-edition" });
});
