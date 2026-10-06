import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { localLatch, localPath } from "../boot/local-latch.ts";

const call = (name: string, args: Record<string, unknown>, home: string) =>
  localLatch({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }, home)
    .then(r => (r as { result: { content: { text: string }[]; isError?: boolean } }).result);

test("an event install's wiki lives on this machine: ~/Plow/... reads and writes under its home", async t => {
  const home = await mkdtemp(join(tmpdir(), "local-latch-"));
  t.after(() => rm(home, { recursive: true, force: true }));
  const missing = await call("plow_read_file", { path: "~/Plow/wiki/wiki.toml" }, home);
  assert.equal(missing.isError, true);
  assert.match(missing.content[0]!.text, /ENOENT/, "run_gate reads ENOENT as a reachable 'Mac' with no wiki yet");
  const wrote = JSON.parse((await call("plow_write_file", { path: "~/Plow/wiki/wiki.toml", content: "[roots]\n" }, home)).content[0]!.text);
  assert.equal(wrote.path, join(home, "Plow/wiki/wiki.toml"));
  assert.equal(await readFile(wrote.path, "utf8"), "[roots]\n");
  const read = JSON.parse((await call("plow_read_file", { path: "~/Plow/wiki/wiki.toml" }, home)).content[0]!.text);
  assert.equal(read.content, "[roots]\n");
});

test("nothing outside its home, and every Mac-only tool says there is no Mac", async t => {
  const home = await mkdtemp(join(tmpdir(), "local-latch-"));
  t.after(() => rm(home, { recursive: true, force: true }));
  for (const path of ["/etc/passwd", "~/../../etc/passwd", "../secret"]) {
    assert.equal(localPath(path, home), null, path);
    assert.equal((await call("plow_read_file", { path }, home)).isError, true, path);
    assert.equal((await call("plow_write_file", { path, content: "x" }, home)).isError, true, path);
  }
  // An error, not a result: connectors.ts reads any plow_device_status result as a Mac
  // that answers, and would refuse plow_google for the whole install.
  for (const [name, args] of [["plow_device_status", {}], ["plow_run_command", { argv: ["plow-gog", "gmail", "search"] }],
    ["plow_run_command", { argv: ["sh", "-c", "id"] }], ["plow_read_skill", { name: "imessage" }], ["plow_browser_open", {}]] as const) {
    const answer = await localLatch({ jsonrpc: "2.0", id: 7, method: "tools/call", params: { name, arguments: args } }, home) as Record<string, any>;
    assert.equal("result" in answer, false, name);
    assert.match(answer.error.message, /No Mac on this install.*plow_google and plow_slack/, name);
  }
});

test("it answers the MCP handshake the gateway sends, and lists only the wiki's tools", async () => {
  const init = await localLatch({ jsonrpc: "2.0", id: 0, method: "initialize", params: {} });
  assert.deepEqual((init as { result: { capabilities: object } }).result.capabilities, { tools: {} });
  assert.equal(await localLatch({ jsonrpc: "2.0", method: "notifications/initialized" }), null);
  const list = await localLatch({ jsonrpc: "2.0", id: 2, method: "tools/list" });
  assert.deepEqual((list as { result: { tools: { name: string }[] } }).result.tools.map(t => t.name),
    ["plow_read_file", "plow_write_file", "plow_run_command"]);
});
