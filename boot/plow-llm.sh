#!/usr/bin/env bash
# Moves this install's inference between Plow and the owner's own OpenAI
# account. Plow is the default and stays the fallback either way, so a one-click
# install never needs this. Run it as the agent's user in a login shell
# (`docker compose exec agent bash -l`, or SSH on the VM), then restart the
# agent: boot reads the choice from the marker this writes.
set -euo pipefail
marker=/var/lib/plow/llm-provider
openclaw=(node /app/openclaw.mjs)

# The model boot will choose, by boot's own rule (AGENT_PROVIDER, then the marker).
primary() {
  node --input-type=module -e 'import { llmRoute } from "/opt/plow/boot/llm.js"; console.log(llmRoute().route.primary);'
}

# The paper's scheduled jobs are registered with a model, so they are
# registered again under the one boot will choose. Before setup there are none.
reregister() {
  [ -f /var/lib/plow/pt/config.json ] || return 0
  PT_MODEL="$(primary)" /opt/plow/skills/pt-dashboard/scripts/register_crons.py \
    || echo "plow-llm: the paper's jobs keep their old model until they are registered again" >&2
}

case "${1:-status}" in
  openai)
    "${openclaw[@]}" models auth login --provider openai --device-code
    if ! "${openclaw[@]}" models list --provider openai | grep -q 'gpt-6-luna'; then
      echo "plow-llm: this OpenAI account does not offer gpt-6-luna; staying on Plow" >&2
      exit 1
    fi
    printf 'openai\n' > "$marker"
    reregister
    ;;
  plow)
    rm -f "$marker"
    reregister
    ;;
  sync)
    reregister
    ;;
  status)
    echo "marker: $(cat "$marker" 2>/dev/null || echo none)"
    echo "AGENT_PROVIDER: ${AGENT_PROVIDER:-unset} (overrides the marker)"
    echo "next boot: $(primary)"
    exit 0
    ;;
  *)
    echo "usage: plow-llm openai | plow | sync | status" >&2
    exit 2
    ;;
esac
echo "plow-llm: restart the agent to apply it (locally: docker compose restart agent)"
