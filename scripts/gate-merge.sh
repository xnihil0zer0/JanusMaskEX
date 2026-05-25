#!/usr/bin/env bash
# gate-merge.sh — merge a gated task branch back to master.
#
# Usage:  scripts/gate-merge.sh <task-id>
#
# Runs verification ONE MORE TIME on the worktree, then merges the branch
# into master (from the main repo, not the worktree). On success, removes
# the worktree and deletes the branch.
#
# Refuses to merge if:
#   - Verification fails in the worktree
#   - The branch has merge conflicts with master
#   - Master has diverged and would need a non-fast-forward merge

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

TASK_ID="${1:-}"
if [ -z "$TASK_ID" ]; then
    echo "Usage: $0 <task-id>" >&2
    exit 2
fi

if ! [[ "$TASK_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "ERROR: invalid task-id" >&2
    exit 2
fi

BRANCH="task/$TASK_ID"
WORKTREE=".worktrees/$TASK_ID"

if [ ! -d "$WORKTREE" ]; then
    echo "ERROR: worktree '$WORKTREE' does not exist" >&2
    exit 1
fi

if ! git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
    echo "ERROR: branch '$BRANCH' does not exist" >&2
    exit 1
fi

# --- Run verification in the worktree ---
echo "Running final verification in worktree..."
echo ""
(cd "$WORKTREE" && "$SCRIPT_DIR/gate-verify.sh") || {
    echo ""
    echo "Verification failed. Merge BLOCKED." >&2
    exit 1
}

# --- Check for uncommitted changes in worktree ---
if [ -n "$(cd "$WORKTREE" && git status --porcelain)" ]; then
    echo "" >&2
    echo "ERROR: worktree has uncommitted changes. Commit them first." >&2
    (cd "$WORKTREE" && git status --short)
    exit 1
fi

# --- Attempt fast-forward merge to main ---
echo ""
echo "Merging $BRANCH into main (fast-forward only)..."

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "ERROR: main repo is on '$CURRENT_BRANCH', expected 'main'" >&2
    echo "       switch to main in the main repo before merging" >&2
    exit 1
fi

if ! git merge --ff-only "$BRANCH"; then
    echo "" >&2
    echo "ERROR: non-fast-forward merge — main has moved ahead." >&2
    echo "       rebase the branch first:" >&2
    echo "         cd $WORKTREE && git rebase main" >&2
    exit 1
fi

# --- Clean up worktree and branch ---
echo ""
echo "Cleaning up worktree and branch..."
git worktree remove "$WORKTREE"
git branch -d "$BRANCH"

NEW_HEAD=$(git rev-parse --short HEAD)
echo ""
echo "================================================================"
echo "  Merged $BRANCH into main"
echo "  main is now at $NEW_HEAD"
echo "================================================================"
