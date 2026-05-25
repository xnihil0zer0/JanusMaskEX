#!/usr/bin/env bash
# gate-commit.sh — verify and commit changes in a delegated worktree.
#
# Usage:  scripts/gate-commit.sh "<commit message>"
#
# Runs gate-verify.sh first. Only commits if verification passes.
# Must be run from inside a git worktree with changes to commit.

set -euo pipefail

# Find script directory (handles being called from any cwd)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MESSAGE="${1:-}"
if [ -z "$MESSAGE" ]; then
    echo "Usage: $0 \"<commit message>\"" >&2
    exit 2
fi

# Find the worktree root
WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$WORKTREE_ROOT" ]; then
    echo "ERROR: not inside a git worktree" >&2
    exit 2
fi
cd "$WORKTREE_ROOT"

# Check there's something to commit
if git diff --quiet HEAD 2>/dev/null && [ -z "$(git status --porcelain)" ]; then
    echo "ERROR: no changes to commit" >&2
    exit 1
fi

# Enforce that manual commits cannot include .py files directly
# (They must be integrated via gate-integration.sh)
STAGED_PY=$(git diff --cached --name-only | grep "\.py$" || true)
if [ -n "$STAGED_PY" ]; then
    # We only allow the auto-commit from gate-integration.sh to commit .py files
    if ! echo "$MESSAGE" | grep -q "Auto-committed via gate-integration.sh"; then
        echo "ERROR: Cannot manually commit Python files." >&2
        echo "All code must pass through the JanusMask dual-agent fuzzing pipeline" >&2
        echo "and be integrated via scripts/gate-integration.sh." >&2
        echo "Offending files:" >&2
        echo "$STAGED_PY" | sed 's/^/  /' >&2
        exit 1
    fi
fi

# Show what will be committed
echo "Changes to commit:"
git status --short
echo ""

# Run the verification gate
if ! "$SCRIPT_DIR/gate-verify.sh"; then
    echo "" >&2
    echo "Verification failed. Commit BLOCKED." >&2
    exit 1
fi

echo ""
echo "Skipping blind stage. Ensure you have run 'git add <files>' manually."

# Show what will actually be committed (after gitignore filtering)
STAGED=$(git diff --cached --name-only | wc -l)
if [ "$STAGED" -eq 0 ]; then
    echo "ERROR: nothing staged — please stage your changes manually." >&2
    exit 1
fi
echo "Staged $STAGED file(s)"

# Commit
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git commit -m "$MESSAGE"

echo ""
echo "================================================================"
echo "  Committed on branch: $BRANCH"
echo "  Commit:              $(git rev-parse --short HEAD)"
echo "================================================================"
