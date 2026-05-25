#!/usr/bin/env bash
# SessionStart meta-hook. Emits current-phase/task context as stdout text
# (becomes session additionalContext). See hooks-augmented §3.1.
set -u
PROJ="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
# Drain stdin (Claude Code sends a JSON payload even for SessionStart).
cat >/dev/null 2>&1 || true
exec python3 "$PROJ/scripts/impl_context_emit.py" session_start
