import assert from "node:assert/strict";
import { test } from "node:test";
import type { Identity } from "../boot/config.ts";
import { skillEnv } from "../boot/skill-env.ts";

const self = { type: "agent" as const, relationship: "self", line: { uid: "ln_phone" } };
const owner = { type: "member" as const, role: "owner", uid: "mem_owner" };
const identity: Identity = {
  agent: { name: "The Founder Times" },
  line: { uid: "ln_phone" },
  mcp_url: "https://relay.test/mcp/dev_1",
  chats: [{ uid: "cht_dm", status: "active", participants: [self, owner] }],
};

test("exports the Mac relay and the owner's DM for the memo scripts", () => {
  assert.deepEqual(skillEnv(identity), { PLOW_MCP_URL: "https://relay.test/mcp/dev_1", PLOW_HOME_CHANNEL: "cht_dm" });
});

test("groups, other lines and closed chats are not the owner's DM", () => {
  const env = skillEnv({ ...identity, chats: [
    { uid: "cht_group", status: "active", participants: [self, owner, { type: "member", role: "member", uid: "mem_guest" }] },
    { uid: "cht_mail", status: "active", participants: [{ ...self, line: { uid: "ln_mail", provider_type: "email" } }, owner] },
    { uid: "cht_old", status: "archived", participants: [self, owner] },
  ] });
  assert.equal(env.PLOW_HOME_CHANNEL, "");
});

test("an ambiguous owner or a missing relay leaves the variables blank, not stale", () => {
  const env = skillEnv({ ...identity, mcp_url: null, chats: [
    { uid: "cht_a", status: "active", participants: [self, owner] },
    { uid: "cht_b", status: "active", participants: [self, owner] },
  ] });
  assert.deepEqual(env, { PLOW_MCP_URL: "", PLOW_HOME_CHANNEL: "" });
});
