#!/usr/bin/env bash
# UserPromptSubmit meta-hook. Injects per-turn status bar as stdout text.
# See hooks-augmented §3.1.
set -u
PROJ="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cat >/dev/null 2>&1 || true
exec python3 "$PROJ/scripts/impl_context_emit.py" prompt
