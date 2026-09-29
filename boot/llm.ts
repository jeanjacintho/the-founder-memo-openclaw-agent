import { readFileSync } from "node:fs";

// Where this install's inference goes. Plow is every install's provider: a
// one-click install has nothing to set and never leaves it. The owner of one
// install can move it to their own OpenAI account (`plow-llm openai` signs in
// and leaves the marker below) or name one with AGENT_PROVIDER and
// AGENT_MODEL. Plow's model stays behind as the fallback, so a
// spent quota or an expired sign-in degrades to Plow instead of to silence.
export const PLOW_MODEL = "plow/openai/gpt-6-luna";
export const LLM_MARKER = "/var/lib/plow/llm-provider";

export type LlmProvider = "plow" | "openai" | "openrouter";
export type LlmRoute = { provider: LlmProvider; primary: string; fallbacks: string[] };
export const PLOW_ROUTE: LlmRoute = { provider: "plow", primary: PLOW_MODEL, fallbacks: [] };

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
  return { route: { provider: chosen, primary: `${chosen}/${model}`, fallbacks: [PLOW_MODEL] } };
}
