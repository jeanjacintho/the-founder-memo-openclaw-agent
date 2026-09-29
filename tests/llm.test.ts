import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { llmRoute, modelName, PLOW_LUNA, PLOW_MODEL, PLOW_ROUTE, readLlmMarker } from "../boot/llm.ts";

test("a one-click install, with no marker and no environment, stays on Plow", () => {
  assert.deepEqual(llmRoute({}, undefined), { route: PLOW_ROUTE });
  // Sol on Plow; Plow's Luna answers if Plow cannot serve Sol, instead of silence.
  assert.deepEqual(PLOW_ROUTE, { provider: "plow", primary: "plow/openai/gpt-6-sol", fallbacks: ["plow/openai/gpt-6-luna"] });
});

test("the owner's OpenAI sign-in moves inference to their account with Plow as the fallback", () => {
  assert.deepEqual(llmRoute({}, "openai"), {
    route: { provider: "openai", primary: "openai/gpt-6-sol", fallbacks: [PLOW_MODEL, PLOW_LUNA] },
  });
});

test("AGENT_PROVIDER outranks the marker, and AGENT_MODEL names the model with or without its prefix", () => {
  assert.deepEqual(llmRoute({ AGENT_PROVIDER: "plow" }, "openai").route, PLOW_ROUTE);
  assert.deepEqual(llmRoute({ AGENT_PROVIDER: "openrouter", AGENT_MODEL: "openai/gpt-6-luna" }, undefined).route,
    { provider: "openrouter", primary: "openrouter/openai/gpt-6-luna", fallbacks: [PLOW_MODEL, PLOW_LUNA] });
  assert.equal(llmRoute({ AGENT_PROVIDER: "OpenAI", AGENT_MODEL: "openai/gpt-6-sol" }, undefined).route.primary, "openai/gpt-6-sol");
});

test("the owner's OpenAI account runs chat and papers on Sol", () => {
  // Measured live: Luna read every skill, then gave up the paper before its
  // first browser call; Sol researched, rendered, posted and printed it.
  assert.equal(llmRoute({}, "openai").route.primary, "openai/gpt-6-sol");
  assert.equal(llmRoute({ AGENT_MODEL: "gpt-6-luna" }, "openai").route.primary, "openai/gpt-6-luna");
});

test("the agent names the model it actually runs on", () => {
  assert.equal(modelName(PLOW_ROUTE), "GPT-6 Sol (`openai/gpt-6-sol`) on Plow");
  assert.equal(modelName(llmRoute({}, "openai").route), "GPT-6 Sol (`openai/gpt-6-sol`) on the owner's OpenAI account");
  assert.equal(modelName(llmRoute({ AGENT_PROVIDER: "openrouter", AGENT_MODEL: "x/y" }, undefined).route),
    "`openrouter/x/y` on OpenRouter");
});

test("a provider this image cannot use stays on Plow and says why", () => {
  const openrouter = llmRoute({ AGENT_PROVIDER: "openrouter" }, undefined);
  assert.deepEqual(openrouter.route, PLOW_ROUTE);
  assert.match(openrouter.problem!, /openrouter needs AGENT_MODEL/);
  const unknown = llmRoute({}, "anthropic");
  assert.deepEqual(unknown.route, PLOW_ROUTE);
  assert.match(unknown.problem!, /unknown provider "anthropic"/);
});

test("the marker is read trimmed, and a missing marker is no marker", async t => {
  const dir = await mkdtemp(join(tmpdir(), "plow-llm-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  assert.equal(readLlmMarker(join(dir, "absent")), undefined);
  await writeFile(join(dir, "llm-provider"), "openai\n");
  assert.equal(readLlmMarker(join(dir, "llm-provider")), "openai");
  await writeFile(join(dir, "empty"), "\n");
  assert.equal(readLlmMarker(join(dir, "empty")), undefined);
});
