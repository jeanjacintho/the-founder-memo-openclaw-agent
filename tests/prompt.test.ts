import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { test } from "node:test";
import { renderConfig } from "../boot/config.ts";
import { probeIdentity } from "../boot/probe-fixture.ts";
import { renderPrompt } from "../boot/prompt.ts";
import { llmRoute, roleModels } from "../boot/llm.ts";

const prompt = await readFile(new URL("../prompt/AGENTS.md", import.meta.url), "utf8");
const maxChars = renderConfig(probeIdentity, "http://api").agents.defaults.bootstrapMaxChars;

test("the tournament dispatch contract uses the configured writer and critic routes", async () => {
  const roles = roleModels({
    MEMO_MODEL_WRITER: "plow/anthropic/writer-fixture", MEMO_MODEL_WRITER_PRICE: "5,25",
    MEMO_MODEL_CRITIC: "plow/openai/critic-fixture", MEMO_MODEL_CRITIC_PRICE: "1,10",
  })!;
  const rendered = prompt.replaceAll("{{writer_model}}", roles.writer).replaceAll("{{critic_model}}", roles.critic);
  assert.match(rendered, /writer model is `plow\/anthropic\/writer-fixture`/);
  assert.match(rendered, /critic\s+model is `plow\/openai\/critic-fixture`/);
  assert.match(rendered, /Pass these exact ids as `sessions_spawn.model`/);
  assert.doesNotMatch(rendered, /\{\{(?:writer|critic)_model\}\}/);
  const skill = await readFile(new URL("../skills/memo-tournament/SKILL.md", import.meta.url), "utf8");
  const loop = skill.split("### Mechanical loop (authoritative)")[1].split("### ")[0];
  assert.match(loop, /five writer children \(`model`: the writer model\)/);
  assert.match(loop, /critics:[\s\S]*\(`model`: the critic model\)/);
  assert.match(loop, /one culler child \(`model`: the writer\s+model\)/);
});

test("unset role models render the selected boot route for both roles", () => {
  const route = llmRoute({ AGENT_PROVIDER: "openai", AGENT_MODEL: "chat-fixture" }, "").route;
  const roles = roleModels({}) ?? { writer: route.primary, critic: route.primary };
  const rendered = prompt.replaceAll("{{writer_model}}", roles.writer).replaceAll("{{critic_model}}", roles.critic);
  assert.match(rendered, /writer model is `openai\/chat-fixture`/);
  assert.match(rendered, /critic\s+model is `openai\/chat-fixture`/);
});

test("dashboard address comes from agent identity, including absence", async () => {
  assert.equal(await renderPrompt(prompt, null, "test-token", "https://dashboard.example/agent"),
    `${prompt}\nYour dashboard is https://dashboard.example/agent. Give that exact address when asked; never guess a dashboard URL.\n`);
  assert.equal(await renderPrompt(prompt, null, "test-token", null),
    `${prompt}\nYou have no dashboard. Say so when asked for its URL; never guess one.\n`);
});

for (const format of ["json", "sse", "oversized", "missing", "invalid", "unavailable", "redirect"]) {
  test(`Latch initialize instructions: ${format}`, async () => {
    let requests = 0;
    const server = createServer(async (request, response) => {
      requests++;
      assert.equal(request.method, "POST");
      assert.equal(request.headers.authorization, "Bearer test-token");
      assert.equal(request.headers.accept, "application/json, text/event-stream");
      let body = "";
      for await (const chunk of request) body += chunk;
      const rpc = JSON.parse(body);
      assert.equal(rpc.method, "initialize");
      assert.equal(rpc.params.protocolVersion, "2025-06-18");
      const instructions = format === "oversized" ? "A".repeat(8_000) + "OMIT"
        : "Use plow_list_skills to discover the owner's Mac skills.";
      const result = format === "missing" ? {} : { instructions: format === "invalid" ? {} : instructions };
      const payload = JSON.stringify({ jsonrpc: "2.0", id: rpc.id, result });
      response.writeHead(format === "unavailable" ? 503 : format === "redirect" ? 307 : 200, {
        "Content-Type": format === "sse" ? "text/event-stream" : "application/json",
        ...(format === "redirect" ? { Location: "/other" } : {}),
      });
      response.end(format === "sse" ? `event: message\ndata: ${payload}\n\n` : payload);
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      assert.ok(address && typeof address !== "string");
      const rendered = await renderPrompt(prompt, `http://127.0.0.1:${address.port}`, "test-token");
      const expectedInstructions = format === "oversized" ? "A".repeat(8_000)
        : "Use plow_list_skills to discover the owner's Mac skills.";
      const base = `${prompt}\nYou have no dashboard. Say so when asked for its URL; never guess one.\n`;
      assert.equal(rendered, ["json", "sse", "oversized"].includes(format)
        ? `${base}\nInstructions from your owner's Mac through Latch (up to 8,000 characters):\n\n\`\`\`text\n${expectedInstructions}\n\`\`\`\n`
        : base);
      assert.ok(rendered.length <= maxChars, "workspace instructions fit the per-file context cap");
      assert.equal(requests, 1);
    } finally {
      await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    }
  });
}

test("the prompt directs existing-chat sends to the native tool", () => {
  assert.ok(!prompt.includes("plow_send_message"));
  assert.ok(!prompt.includes("Do not use message"));
  assert.doesNotMatch(prompt, /message\(action="send"\) is for OTHER conversations/i);
  assert.match(prompt, /message\(action="send"\).*current conversation/i);
  assert.match(prompt, /accountId/);
  assert.match(prompt, /plow_start_thread/);
});
