// An event install has no owner Mac. This stands in for Latch on 127.0.0.1:18790
// (where mcp-bridge.ts would proxy the owner's Mac) with the one thing the memo
// needs a Mac for besides research: its wiki, kept on this machine under
// LOCAL_HOME (`~` there). Research has its own no-Mac path (plow_google,
// plow_slack). Every Mac-only tool is a JSON-RPC error, never a result: the
// plugin's Latch probe (plugin/connectors.ts) counts any result from
// plow_device_status as "the Mac answers", which would turn plow_google off.
import { execFile } from "node:child_process";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, resolve } from "node:path";

export const LOCAL_HOME = "/var/lib/plow/home";
const VENV = "/opt/plow/pt-venv/bin";
// wiki: the plow-wiki CLI. python3 -c: wiki.py's conditional page update. Neither adds
// a capability: the agent already has exec on this machine; this only keeps the
// wiki's commands where its pages are.
export const COMMANDS: Record<string, string> = { wiki: `${VENV}/wiki`, python3: `${VENV}/python3` };
const NO_MAC = "No Mac on this install (an event install): this tool reads the owner's Mac. " +
  "Research their mail, calendar and Slack with plow_google and plow_slack instead.";

type Rpc = { jsonrpc?: string; id?: number | string | null; method?: string; params?: { name?: string; arguments?: Record<string, unknown> } };
const text = (value: unknown, isError = false) =>
  ({ content: [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value) }], ...(isError ? { isError } : {}) });

/** A `~/...` or absolute path inside LOCAL_HOME, or null for anything outside it. */
export function localPath(path: unknown, home = LOCAL_HOME): string | null {
  if (typeof path !== "string" || !path) return null;
  const full = resolve(home, path.startsWith("~/") ? path.slice(2) : path === "~" ? "." : path);
  return full === home || full.startsWith(home + "/") ? full : null;
}

function run(argv: string[], home: string): Promise<{ exit_code: number; output: string; status: string }> {
  return new Promise(done => execFile(COMMANDS[argv[0]!]!, argv.slice(1), {
    cwd: home, env: { HOME: home, PATH: `${VENV}:/usr/bin:/bin` }, timeout: 120_000, maxBuffer: 4 << 20,
  }, (error, stdout, stderr) => done({
    exit_code: error ? (typeof error.code === "number" ? error.code : 1) : 0,
    output: `${stdout}${stderr}`, status: "completed",
  })));
}

/** One JSON-RPC message in, its answer out (null for a notification). */
export async function localLatch(rpc: Rpc, home = LOCAL_HOME): Promise<object | null> {
  const reply = (result: object) => ({ jsonrpc: "2.0", id: rpc.id ?? null, result });
  const fail = (message: string) => ({ jsonrpc: "2.0", id: rpc.id ?? null, error: { code: -32601, message } });
  if (rpc.method?.startsWith("notifications/")) return null;
  if (rpc.method === "initialize") {
    return reply({ protocolVersion: "2025-03-26", capabilities: { tools: {} }, serverInfo: { name: "plow-local", version: "1" } });
  }
  if (rpc.method === "ping") return reply({});
  if (rpc.method === "tools/list") {
    const path = { type: "object", required: ["path"], properties: { path: { type: "string" } } };
    return reply({ tools: [
      { name: "plow_read_file", description: "Read a file of this install's wiki (~/Plow/wiki).", inputSchema: path },
      { name: "plow_write_file", description: "Write a file of this install's wiki (~/Plow/wiki).",
        inputSchema: { ...path, required: ["path", "content"], properties: { ...path.properties, content: { type: "string" } } } },
      { name: "plow_run_command", description: "Run the wiki CLI (argv [\"wiki\", ...]) on this install's wiki.",
        inputSchema: { type: "object", required: ["argv"], properties: { argv: { type: "array", items: { type: "string" } } } } },
    ] });
  }
  if (rpc.method !== "tools/call") return fail("method not found");
  const args = rpc.params?.arguments ?? {};
  switch (rpc.params?.name) {
    case "plow_read_file": {
      const file = localPath(args.path, home);
      if (!file) return reply(text(`outside this install's home: ${String(args.path)}`, true));
      try { return reply(text({ content: await readFile(file, "utf8") })); }
      catch { return reply(text(`ENOENT: no such file: ${String(args.path)}`, true)); }
    }
    case "plow_write_file": {
      const file = localPath(args.path, home);
      if (!file || typeof args.content !== "string") return reply(text(`refused: ${String(args.path)}`, true));
      await mkdir(dirname(file), { recursive: true });
      await writeFile(file, args.content);
      return reply(text({ path: file }));
    }
    case "plow_run_command": {
      const argv = args.argv;
      if (!Array.isArray(argv) || !argv.every(a => typeof a === "string") || !COMMANDS[argv[0]]) return fail(NO_MAC);
      await mkdir(home, { recursive: true });
      return reply(text(await run(argv as string[], home)));
    }
    default:
      return fail(NO_MAC);
  }
}

if (process.argv[1]?.endsWith("local-latch.js")) {
  const tokens = [process.env.PLOW_MCP_BRIDGE_TOKEN, process.env.PLOW_AGENT_TOKEN].filter(Boolean).map(t => `Bearer ${t}`);
  if (!tokens.length) throw new Error("PLOW_MCP_BRIDGE_TOKEN or PLOW_AGENT_TOKEN is required");
  createServer(async (request, response) => {
    if (!tokens.includes(request.headers.authorization ?? "")) { response.writeHead(401).end("Unauthorized"); return; }
    const chunks: Buffer[] = [];
    for await (const chunk of request) chunks.push(chunk);
    let answer: object | null;
    try { answer = await localLatch(JSON.parse(Buffer.concat(chunks).toString() || "{}")); }
    catch { response.writeHead(400).end("Bad request"); return; }
    if (!answer) { response.writeHead(202).end(); return; }
    response.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify(answer));
  }).listen(18790, "127.0.0.1", () => process.send?.("ready"));
}
