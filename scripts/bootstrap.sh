#!/usr/bin/env bash
# scripts/bootstrap.sh — initialize gitignored agent-tool configs from .template siblings.
#
# One-time setup. Idempotent: only copies templates when the live path is
# absent. Warns (but does not fail) on copy errors so the script remains
# safe to re-run during partial setups.
#
# Style mirrors scripts/setup-git-identity.sh (set -u, ${VAR:-fallback}
# project-dir derivation, mkdir -p, simple echo messaging).

set -u

PROJ="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

mkdir -p "$PROJ/.claude" "$PROJ/.gemini" || {
  echo "WARNING: failed to create config dirs under $PROJ" >&2
}

_install_template() {
  # $1 = relative live path, $2 = relative template path
  local live="$PROJ/$1"
  local tpl="$PROJ/$2"
  if [ -f "$live" ]; then
    echo "$1 already exists, skipping."
    return 0
  fi
  if [ ! -f "$tpl" ]; then
    echo "WARNING: template $2 not found, $1 not initialized" >&2
    return 0
  fi
  if cp "$tpl" "$live" 2>/dev/null; then
    echo "Initialized $1 from template."
  else
    echo "WARNING: failed to copy $2 -> $1 (permissions?)" >&2
  fi
}

_install_template ".claude/settings.local.json" ".claude/settings.local.json.template"
_install_template ".gemini/settings.json"       ".gemini/settings.json.template"

# State tree materialization (W116) — gitignored state/ tree is recreated
# from tracked templates so a fresh clone has a working pre-write gate +
# orchestrator state file. Idempotent: every step checks existence first.
mkdir -p \
  "$PROJ/state/tasks/queued" \
  "$PROJ/state/tasks/processed" \
  "$PROJ/state/tasks/blocked" \
  "$PROJ/state/sessions" \
  "$PROJ/state/control/autowork" \
  "$PROJ/state/hooks" 2>/dev/null || {
    echo "WARNING: failed to create state/ subdirs under $PROJ" >&2
}

# Autowork allowlist safety baseline (REPL-1/G-EMPTYALLOW) — seed a comment-only
# allowlist so a fresh clone is DENY-ALL by default. The autowork daemon treats
# both a missing file AND a comment-only file as deny-all; only an explicit
# uncommented slug line permits auto-promotion. Operators add slugs to opt in.
if [ ! -f "$PROJ/state/control/autowork/auto_promote.allowlist" ]; then
  if printf '%s\n' \
       '# autowork auto-promote allowlist — one slug per line.' \
       '# SAFETY BOUNDARY: empty/comment-only = deny-all (daemon dispatches nothing).' \
       '# Add a brief slug (the brief_hooks_<slug>.md stem) on its own line to opt in.' \
       > "$PROJ/state/control/autowork/auto_promote.allowlist" 2>/dev/null; then
    echo "Initialized state/control/autowork/auto_promote.allowlist (comment-only deny-all baseline)."
  else
    echo "WARNING: failed to seed auto_promote.allowlist" >&2
  fi
else
  echo "state/control/autowork/auto_promote.allowlist already exists, skipping."
fi

_install_template "state/impl_preserve.md" "config/impl_preserve.template.md"

if [ ! -f "$PROJ/state/impl_progress.jsonl" ]; then
  if : > "$PROJ/state/impl_progress.jsonl" 2>/dev/null; then
    echo "Initialized state/impl_progress.jsonl (empty)."
  else
    echo "WARNING: failed to touch state/impl_progress.jsonl" >&2
  fi
else
  echo "state/impl_progress.jsonl already exists, skipping."
fi

if [ ! -f "$PROJ/state/STATE.json" ]; then
  if printf '%s\n' '{"task_id": null, "round": 0, "phase": "idle"}' \
       > "$PROJ/state/STATE.json" 2>/dev/null; then
    echo "Initialized state/STATE.json (idle)."
  else
    echo "WARNING: failed to write state/STATE.json" >&2
  fi
else
  echo "state/STATE.json already exists, skipping."
fi

# Operator memory seed (REPL-9) — copy the clone-survivable memory files
# from local-memory/ into the per-CWD memory slug dir so a fresh clone has
# the operating procedure even though ~/.claude/projects/<slug>/memory/ is not
# part of the checkout. Slug derivation mirrors scripts/impl_pre_write.py:170-172
# (absolute CWD with '/' -> '-', single leading '-'). Warn-don't-fail.
if [ -d "$PROJ/local-memory" ]; then
  _MEM_SLUG="-$(printf '%s' "$PROJ" | sed 's#/#-#g' | sed 's#^-*##')"
  _MEM_DIR="$HOME/.claude/projects/$_MEM_SLUG/memory"
  if mkdir -p "$_MEM_DIR" 2>/dev/null; then
    echo "Seeding operator memory files from local-memory to $_MEM_DIR..."
    if cp -p "$PROJ/local-memory/"*.md "$_MEM_DIR/" 2>/dev/null; then
      echo "Seeded operator memory files at $_MEM_DIR."
    else
      echo "WARNING: failed to seed memory files into $_MEM_DIR" >&2
    fi
  else
    echo "WARNING: failed to create memory slug dir $_MEM_DIR" >&2
  fi
fi

# Python venv preflight (BOOTSTRAP_PREFLIGHT_VENV) — replaces the prior
# next-step echo of "python3 -m venv venv && ./venv/bin/pip install ...".
# Hard preflight: aborts with non-zero exit if python3 is missing. Venv
# creation and pip install are idempotent (guarded on venv/bin/pip
# presence) and warn-don't-fail to preserve the script's re-runnable style.
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found in PATH; see https://www.python.org/downloads/" >&2
  exit 1
fi

# Agent CLI preflight (REPL-4) — warn-don't-fail: bootstrap completes even
# without the agent CLIs (so state/ + configs still land), but the operator is
# told what is missing. Auth is probed best-effort and never blocks.
for _cli in claude gemini; do
  if command -v "$_cli" >/dev/null 2>&1; then
    echo "Found $_cli CLI: $(command -v "$_cli")"
  else
    echo "WARNING: '$_cli' CLI not found in PATH; dispatch will fail until installed." >&2
  fi
done
if command -v claude >/dev/null 2>&1; then
  if ! claude --version >/dev/null 2>&1; then
    echo "WARNING: 'claude --version' failed; verify Claude CLI auth before dispatch." >&2
  fi
fi

(
  cd "$PROJ" || exit 0
  if [ ! -x "venv/bin/pip" ]; then
    if python3 -m venv venv 2>/dev/null; then
      echo "Created venv at $PROJ/venv."
    else
      echo "WARNING: python3 -m venv venv failed; skipping pip install" >&2
    fi
  else
    echo "venv/bin/pip already present, skipping venv creation."
  fi
  # REPL-5: prefer the pinned lock for byte-reproducible installs; fall back to
  # the floor-pinned requirements.txt when no lock is present.
  if [ -f "requirements.lock" ] && [ -x "venv/bin/pip" ]; then
    if ./venv/bin/pip install -r requirements.lock --quiet; then
      echo "Installed requirements.lock (pinned) into $PROJ/venv."
    else
      echo "WARNING: pip install -r requirements.lock failed; venv may be incomplete" >&2
    fi
  elif [ -f "requirements.txt" ] && [ -x "venv/bin/pip" ]; then
    if ./venv/bin/pip install -r requirements.txt --quiet; then
      echo "Installed requirements.txt into $PROJ/venv."
    else
      echo "WARNING: pip install -r requirements.txt failed; venv may be incomplete" >&2
    fi
  fi
)

echo ""
echo "Bootstrap complete. Project dir: $PROJ"
echo "Next steps:"
echo "  - Set git identity:  scripts/setup-git-identity.sh 'You' 'you@host'"
echo "  - Verify Claude/Gemini CLI auth (oauth tokens are user-scoped, not project)"
echo "  - chmod +x scripts/*.sh if needed"
echo "  - python3 -m pytest tests/adversarial -q  (smoke check)"
