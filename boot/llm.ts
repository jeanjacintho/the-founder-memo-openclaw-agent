import { readFileSync } from "node:fs";

// Where this install's inference goes. Plow is every install's provider: a
// one-click install has nothing to set and never leaves it. The owner of one
// install can move it to their own OpenAI account (`plow-llm openai` signs in
// and leaves the marker below) or name one with AGENT_PROVIDER and
// AGENT_MODEL. Plow's model stays behind as the fallback, so a
// spent quota or an expired sign-in degrades to Plow instead of to silence.
export const PLOW_MODEL = "plow/openai/gpt-6-sol";
// Plow's Luna answers when Plow cannot serve Sol, instead of silence.
export const PLOW_LUNA = "plow/openai/gpt-6-luna";
export const LLM_MARKER = "/var/lib/plow/llm-provider";

export type LlmProvider = "plow" | "openai" | "openrouter";
export type LlmRoute = { provider: LlmProvider; primary: string; fallbacks: string[] };
export const PLOW_ROUTE: LlmRoute = { provider: "plow", primary: PLOW_MODEL, fallbacks: [PLOW_LUNA] };

// OpenRouter has no model this image could guess, so it needs AGENT_MODEL.
// On the owner's OpenAI account, Sol: measured live, Luna read every skill and
// then gave up the paper before its first browser call; Sol researched,
// rendered, posted and printed the same edition.
const DEFAULT_MODEL: Partial<Record<LlmProvider, string>> = { openai: "gpt-6-sol" };

const WHERE: Record<LlmProvider, string> = {
  plow: "on Plow", openai: "on the owner's OpenAI account", openrouter: "on OpenRouter",
};

/** How the agent names its own model when asked: `{{model}}` in AGENTS.md. */
export function modelName(route: LlmRoute): string {
  const id = route.primary.replace(/^plow\//, "");
  const family = /gpt-6-(\w+)$/.exec(id)?.[1];
  const name = family ? `GPT-6 ${family[0].toUpperCase()}${family.slice(1)} (\`${id}\`)` : `\`${id}\``;
  return `${name} ${WHERE[route.provider]}`;
}

export function readLlmMarker(path = LLM_MARKER): string | undefined {
  try {
    return readFileSync(path, "utf8").trim() || undefined;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw error;
  }
}

/** AGENT_PROVIDER wins over the marker; anything unusable falls back to Plow and says why. */
export function llmRoute(env: NodeJS.ProcessEnv = process.env, marker = readLlmMarker()): { route: LlmRoute; problem?: string } {
  const chosen = (env.AGENT_PROVIDER?.trim() || marker || "plow").toLowerCase();
  if (chosen === "plow") return { route: PLOW_ROUTE };
  if (chosen !== "openai" && chosen !== "openrouter") {
    return { route: PLOW_ROUTE, problem: `unknown provider ${JSON.stringify(chosen)}, staying on Plow` };
  }
  const model = (env.AGENT_MODEL?.trim() || DEFAULT_MODEL[chosen])?.replace(new RegExp(`^${chosen}/`), "");
  if (!model) return { route: PLOW_ROUTE, problem: `${chosen} needs AGENT_MODEL, staying on Plow` };
  return { route: { provider: chosen, primary: `${chosen}/${model}`, fallbacks: [PLOW_MODEL, PLOW_LUNA] } };
}

// The memo tournament's writer and critic, passed per child at spawn time.
// Both roles are required when boot renders the memo prompt. Each
// is a Plow model carrying its USD-per-million-token price, so run_cost can price
// each child's transcript usage calls and check the nightly dollar ceiling; a critic
// from the writer's own provider would share the writer's blind spots.
export type RoleModel = { ref: string; id: string; cost: { input: number; output: number; cacheRead: number; cacheWrite: number } };
export type MemoRoles = { writer: RoleModel; critic: RoleModel };

function roleModel(env: NodeJS.ProcessEnv, role: "WRITER" | "CRITIC"): RoleModel {
  const ref = env[`MEMO_MODEL_${role}`]!.trim();
  const match = /^plow\/([^/]+\/.+)$/.exec(ref);
  if (!match) throw new Error(`MEMO_MODEL_${role} must be a plow/<provider>/<model> id, got ${JSON.stringify(ref)}`);
  const price = (env[`MEMO_MODEL_${role}_PRICE`] ?? "").split(",").map(part => part.trim());
  const [input, output, cacheRead, cacheWrite] = price.map(Number);
  if (price.length !== 4 || price.some(part => part === "") || ![input, output, cacheRead, cacheWrite].every(n => Number.isFinite(n) && n >= 0)) {
    throw new Error(`MEMO_MODEL_${role}_PRICE must be "<input>,<output>,<cacheRead>,<cacheWrite>" USD per million tokens`);
  }
  return { ref, id: match[1], cost: { input, output, cacheRead, cacheWrite } };
}

export function memoRoles(env: NodeJS.ProcessEnv = process.env): MemoRoles | undefined {
  const writerSet = Boolean(env.MEMO_MODEL_WRITER?.trim()), criticSet = Boolean(env.MEMO_MODEL_CRITIC?.trim());
  if (!writerSet && !criticSet) return undefined;
  if (!writerSet || !criticSet) throw new Error("set both MEMO_MODEL_WRITER and MEMO_MODEL_CRITIC, or neither");
  const writer = roleModel(env, "WRITER"), critic = roleModel(env, "CRITIC");
  if (writer.id.split("/")[0] === critic.id.split("/")[0]) throw new Error("critic must be a different provider than writer");
  return { writer, critic };
}

/** The `{{writer_model}}` / `{{critic_model}}` the prompt names, when the roles are set. */
export function roleModels(env: NodeJS.ProcessEnv = process.env): { writer: string; critic: string } {
  const roles = memoRoles(env);
  if (!roles) throw new Error("the memo requires MEMO_MODEL_WRITER and MEMO_MODEL_CRITIC with prices; set both before starting the agent");
  return { writer: roles.writer.ref, critic: roles.critic.ref };
}
