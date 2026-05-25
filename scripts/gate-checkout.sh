#!/usr/bin/env bash
# gate-checkout.sh — create an isolated worktree for a delegated task.
#
# Usage:  scripts/gate-checkout.sh <task-id> [<base-branch>]
#
# Creates:
#   - Branch:    task/<task-id>    (branched from <base-branch>, default: master)
#   - Worktree:  .worktrees/<task-id>
#
# The delegated agent should cd into the worktree and work there. When done,
# run scripts/gate-commit.sh from inside the worktree to verify and commit.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TASK_ID="${1:-}"
BASE_BRANCH="${2:-main}"

if [ -z "$TASK_ID" ]; then
    echo "Usage: $0 <task-id> [<base-branch>]" >&2
    exit 2
fi

# Validate task-id: alphanumeric, dash, underscore only. No path traversal.
if ! [[ "$TASK_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "ERROR: task-id must match ^[a-zA-Z0-9_-]+$" >&2
    exit 2
fi

BRANCH="task/$TASK_ID"
WORKTREE=".worktrees/$TASK_ID"

# Ensure we have the base branch
if ! git rev-parse --verify "$BASE_BRANCH" >/dev/null 2>&1; then
    echo "ERROR: base branch '$BASE_BRANCH' does not exist" >&2
    exit 1
fi

# Ensure the branch doesn't already exist
if git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
    echo "ERROR: branch '$BRANCH' already exists" >&2
    echo "       remove with: git worktree remove $WORKTREE && git branch -D $BRANCH" >&2
    exit 1
fi

# Ensure the worktree path is free
if [ -e "$WORKTREE" ]; then
    echo "ERROR: worktree path '$WORKTREE' already exists" >&2
    exit 1
fi

mkdir -p .worktrees

# Create the worktree on a new branch
git worktree add -b "$BRANCH" "$WORKTREE" "$BASE_BRANCH"

# Absolute path for clarity
ABS_WORKTREE="$REPO_ROOT/$WORKTREE"

echo ""
echo "================================================================"
echo "  Worktree ready"
echo "================================================================"
echo "  Task ID:     $TASK_ID"
echo "  Branch:      $BRANCH"
echo "  Base:        $BASE_BRANCH"
echo "  Path:        $ABS_WORKTREE"
echo ""
echo "  Next steps:"
echo "    cd $ABS_WORKTREE"
echo "    # ... make changes ..."
echo "    $REPO_ROOT/scripts/gate-commit.sh \"commit message\""
echo "================================================================"
