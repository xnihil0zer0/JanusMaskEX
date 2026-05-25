#!/usr/bin/env bash
# gate-integration.sh — enforces that code integrated into the repository
# has passed the full JanusMask dual-agent fuzzing and cross-exam pipeline.
#
# Usage:  scripts/gate-integration.sh <task_id> <target_repo_path>
#
# Example: scripts/gate-integration.sh FI-014 harness/task_decomposer.py

set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <task_id> <target_repo_path>" >&2
    exit 2
fi

TASK_ID="$1"
TARGET_PATH="$2"

# Find the worktree root
WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$WORKTREE_ROOT"

STATE_DIR="${JANUSMASK_STATE_DIR:-$WORKTREE_ROOT/state}"
OUTPUT_FILE="$STATE_DIR/output/${TASK_ID}.py"
TRACK_RECORD="$STATE_DIR/track_record_events.jsonl"

echo "Verifying integration for task: $TASK_ID"

# 1. Check if output file exists
if [ ! -f "$OUTPUT_FILE" ]; then
    echo "ERROR: Output file $OUTPUT_FILE not found." >&2
    echo "The task must complete the JanusMask pipeline first." >&2
    exit 1
fi

# 2. Check track record for clean_success in synthesis
if [ ! -f "$TRACK_RECORD" ]; then
    echo "ERROR: Track record log $TRACK_RECORD not found." >&2
    exit 1
fi

# We look for a JSON line that has "event_type": "clean_success", "book": "synthesis", and "task_id": "TASK_ID"
if ! grep -q "\"task_id\": \"$TASK_ID\"" "$TRACK_RECORD" | grep -q "\"event_type\": \"clean_success\"" "$TRACK_RECORD" 2>/dev/null; then
    # Use python to properly parse and check the JSONL
    if ! python3 -c "
import sys, json
found = False
with open('$TRACK_RECORD', 'r') as f:
    for line in f:
        try:
            ev = json.loads(line)
            if ev.get('task_id') == '$TASK_ID' and ev.get('event_type') == 'clean_success' and ev.get('book') == 'synthesis':
                found = True
                break
        except: pass
if not found:
    sys.exit(1)
"; then
        echo "ERROR: No clean_success synthesis event found for $TASK_ID in track record." >&2
        echo "Code must pass dual-agent AST generation, differential fuzzing, and cross-examination." >&2
        exit 1
    fi
fi

echo "✓ Track record verified: $TASK_ID passed full JanusMask pipeline."

# 3. Integrate code
cp "$OUTPUT_FILE" "$TARGET_PATH"
echo "✓ Integrated code to $TARGET_PATH"

# 4. Commit to Git
git add "$TARGET_PATH"

if git diff --cached --quiet; then
    echo "No changes to commit for $TARGET_PATH (code is identical)."
else
    git commit -m "Integrate validated code for $TASK_ID

Auto-committed via gate-integration.sh after passing dual-agent
AST generation, differential fuzzing, and cross-examination."
    echo "✓ Committed to git."
fi

echo "Integration complete."
exit 0
