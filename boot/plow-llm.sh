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

# The model the paper's jobs run on, by boot's own rule (paperModel).
paper_model() {
  node --input-type=module -e 'import { llmRoute, paperModel } from "/opt/plow/boot/llm.js"; console.log(paperModel(llmRoute().route));'
}

# The paper's scheduled jobs are registered with a model, so they are
# registered again under the one boot will choose. Before setup there are none.
reregister() {
  [ -f /var/lib/plow/pt/config.json ] || return 0
  PT_MODEL="$(paper_model)" /opt/plow/skills/pt-dashboard/scripts/register_crons.py \
    || echo "plow-llm: the paper's jobs keep their old model until they are registered again" >&2
}

# True when the signed-in account's own catalog offers gpt-6-luna. --refresh
# asks the account: the cached catalog never lists subscription models.
offers_luna() {
  "${openclaw[@]}" models list --provider openai --refresh 2>/dev/null \
    | awk '$1 == "openai/gpt-6-luna" && $5 == "yes" { found = 1 } END { exit !found }'
}

case "${1:-status}" in
  openai)
    if offers_luna; then
      echo "plow-llm: already signed in, and the account offers gpt-6-luna"
    else
      "${openclaw[@]}" models auth login --provider openai --device-code
      if ! offers_luna; then
        echo "plow-llm: this OpenAI account does not offer gpt-6-luna; staying on Plow" >&2
        exit 1
      fi
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
