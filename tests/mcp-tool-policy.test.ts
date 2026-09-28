import assert from "node:assert/strict";
import { readdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { test } from "node:test";
import { renderConfig, type Identity } from "../boot/config.ts";

const identity: Identity = {
  agent: { name: "Juniper" }, line: { uid: "ln_phone" },
  chats: [{ uid: "cht_home", status: "active", participants: [
    { type: "agent", relationship: "self", line: { uid: "ln_phone" } },
    { type: "member", role: "owner", uid: "mem_owner" },
  ] }],
};

async function openclawModule(prefix: string): Promise<Record<string, (...args: any[]) => any>> {
  const dist = dirname(fileURLToPath(import.meta.resolve("openclaw")));
  const filename = (await readdir(dist)).find(name => name.startsWith(prefix) && name.endsWith(".mjs"));
  assert.ok(filename, `OpenClaw module ${prefix} exists`);
  return await import(pathToFileURL(join(dist, filename)).href) as Record<string, (...args: any[]) => any>;
}

test("research MCP tools survive server filtering, safe-name materialization and messaging policy", async () => {
  const config = renderConfig({ ...identity, mcp_url: "https://relay.internal/mcp" }, "http://api:8000");
  const filter = await openclawModule("mcp-tool-filter-");
  const safeNames = await openclawModule("agent-bundle-mcp-names-");
  const catalog = await openclawModule("tool-catalog-");
  const policy = await openclawModule("tool-policy-YDdaK0oX");
  const matcherModule = await openclawModule("tool-policy-match-Bv2XOvEF");
  const sourceTools = [
    "plow_browser", "plow_browser_open", "plow_browser_close", "plow_browser_find",
    "plow_get_output", "plow_get_result", "plow_read_file", "plow_read_skill",
    "plow_run_applescript", "plow_run_command", "plow_write_file", "plow_admin_restart",
  ];
  const serverFilter = config.mcp?.servers?.plow?.toolFilter;
  const materializedNames = sourceTools
    .filter(tool => filter.t(serverFilter, tool))
    .map(tool => safeNames.n({ serverName: "plow", toolName: tool, reservedNames: new Set() }));
  assert.ok(!materializedNames.includes("plow__plow_admin_restart"), "the server filter excludes unrelated Latch tools");

  const profile = catalog.a("messaging");
  assert.ok(profile.allow.includes("bundle-mcp"), "messaging selects configured MCP plugin tools");
  const merged = policy.l(profile, config.tools.alsoAllow);
  const effective = policy.o(merged, {
    all: materializedNames,
    byPlugin: new Map([["bundle-mcp", materializedNames]]),
  });
  const allows = matcherModule.r(effective);
  assert.deepEqual(materializedNames, [
    "plow__plow_browser", "plow__plow_browser_open", "plow__plow_browser_close", "plow__plow_browser_find",
    "plow__plow_get_output", "plow__plow_get_result", "plow__plow_read_file", "plow__plow_read_skill",
    "plow__plow_run_applescript", "plow__plow_run_command", "plow__plow_write_file",
  ]);
  for (const name of materializedNames) assert.equal(allows(name), true, `${name} passes the session policy`);
});
