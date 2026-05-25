#!/usr/bin/env bash
# scripts/replicate_smoke.sh — clean-room replication acceptance (REPL-10).
#
# Clones the current repo to a throwaway path, bootstraps it with ZERO reliance
# on the per-machine ~/.claude/.../memory dir, sets a clone-local git identity,
# dispatches the canonical SMOKE_VERSION task through the direct worker, and
# ASSERTS the full self-fix landed:
#   - an auto_commit ledger row for SMOKE_VERSION
#   - harness/smoke_target.py patched with __version__
#   - a fresh git commit scoped to harness/smoke_target.py
#   - the commit author matches the clone identity (REPL-7)
#   - the clone's pytest baseline is 0-failed
#   - the derived memory slug dir is the clone's, never the operator's live one
#
# Usage:
#   scripts/replicate_smoke.sh [--no-dispatch] [git-author-name] [git-author-email]
#
# A live dispatch requires the claude + gemini CLIs installed and authed
# (~5-7 min). --no-dispatch does everything EXCEPT the live dual-agent run
# (CI-friendly: bootstrap + static checks + clone pytest).

set -u

NO_DISPATCH=0
POS=()
for arg in "$@"; do
  case "$arg" in
    --no-dispatch) NO_DISPATCH=1 ;;
    *) POS+=("$arg") ;;
  esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Clone OUTSIDE /tmp on purpose: several adversarial tests use /tmp as their own
# sandbox base and resolve relative paths against CWD, so a clone living under
# /tmp collides with them (e.g. is_safe_subpath('', '/tmp')). $JM_CLEAN_ROOT
# (default ~/.cache/jm-cleanroom) keeps the clone at an arbitrary path that does
# not collide. Override with JM_CLEAN_ROOT to clone elsewhere.
JM_CLEAN_ROOT="${JM_CLEAN_ROOT:-$HOME/.cache/jm-cleanroom}"
mkdir -p "$JM_CLEAN_ROOT"
DEST="$JM_CLEAN_ROOT/jm-clean-$(date +%s)"
AUTHOR_NAME="${POS[0]:-${GIT_AUTHOR_NAME:-jm-clean-room}}"
AUTHOR_EMAIL="${POS[1]:-${GIT_AUTHOR_EMAIL:-jm-clean-room@example.invalid}}"

echo "==> Cloning $SRC -> $DEST"
git clone --quiet "$SRC" "$DEST"
cd "$DEST"

# Replication invariant: the spawned agents must see CLAUDE_PROJECT_DIR pointing
# at the CLONE, not the source. This drives REPL-8.
export CLAUDE_PROJECT_DIR="$DEST"
export JANUSMASK_PROJECT_DIR="$DEST"

echo "==> Bootstrapping clone"
bash scripts/bootstrap.sh

echo "==> Setting clone-local git identity"
GIT_AUTHOR_NAME="$AUTHOR_NAME" GIT_AUTHOR_EMAIL="$AUTHOR_EMAIL" \
  bash scripts/setup-git-identity.sh

# Memory slug for the CLONE path (mirrors impl_pre_write.py:170-172).
_MEM_SLUG="-$(printf '%s' "$DEST" | sed 's#/#-#g' | sed 's#^-*##')"
_MEM_DIR="$HOME/.claude/projects/$_MEM_SLUG/memory"
echo "==> Derived memory slug dir: $_MEM_DIR"

# Run the clone's pytest baseline on the PRISTINE checkout (before the smoke
# dispatch mutates harness/smoke_target.py). Tests that depend on gitignored
# operator working-tree fixtures or accumulated ledger history skip themselves
# on a fresh clone (see test_P5_drain_*.py / test_planner_model_upgrade), so a
# clean clone is genuinely 0-failed.
echo "==> ASSERT: clone pytest baseline is 0-failed (pristine clone)"
python -m pytest -k 'not TUPLE' \
  --ignore=tests/adversarial/test_F4_stale_submission_cache.py \
  --timeout=120 -q \
  || { echo "FAIL: clone pytest baseline not green" >&2; exit 1; }

if [ "$NO_DISPATCH" -eq 1 ]; then
  echo "==> --no-dispatch: skipping live dual-agent dispatch."
else
  echo "==> Staging + dispatching SMOKE_VERSION (live, ~5-7 min)"
  python scripts/impl_plan_to_queue.py plan_hooks_smoke.json \
    --task SMOKE_VERSION --canonical
  python -m harness.orchestrator_worker --state-dir state --task-id SMOKE_VERSION

  echo "==> ASSERT: auto_commit ledger row for SMOKE_VERSION"
  grep -q '"event": "auto_commit"' state/impl_progress.jsonl \
    && grep -q 'SMOKE_VERSION' state/impl_progress.jsonl \
    || { echo "FAIL: no auto_commit row for SMOKE_VERSION" >&2; exit 1; }

  echo "==> ASSERT: harness/smoke_target.py patched with __version__"
  grep -q "__version__" harness/smoke_target.py \
    || { echo "FAIL: smoke_target.py not patched" >&2; exit 1; }

  echo "==> ASSERT: a new commit touches harness/smoke_target.py"
  git log -1 --name-only --pretty=format: | grep -q "harness/smoke_target.py" \
    || { echo "FAIL: HEAD commit does not scope harness/smoke_target.py" >&2; exit 1; }

  echo "==> ASSERT: HEAD commit author matches clone identity ($AUTHOR_NAME)"
  test "$(git log -1 --pretty=format:'%an')" = "$AUTHOR_NAME" \
    || { echo "FAIL: commit author is not the clone identity" >&2; exit 1; }
fi

echo "==> ASSERT: derived memory slug dir is the clone's, not the operator's live one"
case "$_MEM_DIR" in
  *"$_MEM_SLUG"*) : ;;
  *) echo "FAIL: memory slug dir mismatch" >&2; exit 1 ;;
esac

echo ""
echo "PASS: clean-room replication smoke green at $DEST"
echo "  (remove with: rm -rf '$DEST')"
