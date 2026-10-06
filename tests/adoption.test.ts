import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { listen, type TurnIngress } from "../plugin/transport.ts";
import { websocketFixture, checkpointUid } from "./ws-fixture.ts";

for (const accountId of ["chat", "email"]) for (const mode of ["deferred", "incomplete", "adopted"] as const) {
  test(`${accountId}: ${mode} source survives restart without repeating a later reply`, async t => {
    const { root, server, apiBase, abortAfter } = await websocketFixture(t);
    const account = { accountId, apiBase, lineUid: "line", emailLineUid: "line" };
    const sender = { type: "member", uid: "guest", role: "member", display_name: "Guest", provider_key: "+15550000001" };
    const chat = { uid: "thread", status: "active", trusted: false, participants: [sender,
      { type: "agent", relationship: "self", line: { uid: "line" } }] };
    const messages = ["first", "later"].map(uid => ({ uid, direction: "inbound", sender, body: uid, attachments: [], created_at: "2026-10-06T12:00:00Z" }));
    let boot = 0;
    t.mock.method(globalThis, "fetch", async (url: string) => Response.json(
      url.endsWith("/chats") ? { data: [chat], has_more: false } : url.endsWith("/chats/thread") ? chat :
      url.includes("/messages?") ? { data: boot && !url.includes("limit=20") ? [...messages].reverse() : [], has_more: false } : { ticket: "ticket" }));
    server.on("connection", (socket: { send: (text: string) => void }) => {
      if (boot) return;
      for (const message of messages) socket.send(JSON.stringify({ event_type: "message_received", event_id: message.uid,
        chat_id: chat.uid, data: { message } }));
    });
    const turns: string[][] = [];
    let firstIngress: TurnIngress | undefined;
    for (; boot < 2; boot++) {
      const controller = abortAfter();
      const calls: string[] = [];
      turns.push(calls);
      await listen(account, controller.signal, text => {
        if (text === "acked chat=thread message=later" || (boot && text === "acked chat=thread message=first")) controller.abort();
      }, async (_chat, message, _firstContact, _history, ingress) => {
        calls.push(message.uid);
        if (!boot && message.uid === "first") {
          firstIngress = ingress;
          assert.equal(await checkpointUid(root, chat.uid), "first:first");
          return mode === "incomplete" ? "incomplete" : "deferred";
        }
        if (!boot && mode === "adopted") await firstIngress!.onAdopted();
        return "completed";
      });
      assert.equal(await checkpointUid(root, chat.uid), !boot && mode !== "adopted" ? "first:first" : "later");
      if (!boot && mode !== "adopted") {
        const saved = JSON.parse(await readFile(`${root}/plow-checkpoints/thread`, "utf8"));
        assert.deepEqual(saved.recent, ["later"], "the later confirmed reply is durable behind the unfinished source");
      }
    }
    assert.deepEqual(turns, [["first", "later"], mode === "adopted" ? [] : ["first"]]);
  });
}

for (const accountId of ["chat", "email"]) test(`${accountId}: a failed chat fetch leaves buffered work recoverable`, async t => {
  const { root, server, apiBase, abortAfter } = await websocketFixture(t);
  const account = { accountId, apiBase, lineUid: "line", emailLineUid: "line" };
  const sender = { type: "member", uid: "guest", role: "member", display_name: "Guest", provider_key: "+15550000001" };
  const chat = { uid: "thread", status: "active", trusted: false, participants: [sender,
    { type: "agent", relationship: "self", line: { uid: "line" } }] };
  const messages = ["first", "later"].map(uid => ({ uid, direction: "inbound", sender, body: uid }));
  let boot = 0;
  t.mock.method(globalThis, "fetch", async (url: string) => {
    if (url.endsWith("/chats/thread")) return Response.json(chat, { status: boot ? 200 : 503 });
    return Response.json(url.endsWith("/chats") ? { data: [chat], has_more: false } :
      url.includes("/messages?") ? { data: boot && !url.includes("limit=20") ? [...messages].reverse() : [], has_more: false } : { ticket: "ticket" });
  });
  server.on("connection", (socket: { send: (text: string) => void }) => {
    if (!boot) for (const message of messages) socket.send(JSON.stringify({ event_type: "message_received", event_id: message.uid,
      chat_id: chat.uid, data: { message } }));
  });
  const turns: string[] = [];
  for (; boot < 2; boot++) {
    const controller = abortAfter();
    await listen(account, controller.signal, text => {
      if (text.startsWith("transport stopped") || text === "acked chat=thread message=later") controller.abort();
    }, async (_chat, message) => { turns.push(message.uid); return "completed"; });
    assert.equal(await checkpointUid(root, chat.uid), boot ? "later" : "first:first");
  }
  assert.deepEqual(turns, ["first", "later"]);
});
