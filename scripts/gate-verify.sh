#!/usr/bin/env bash
# gate-verify.sh — run verification checks for a delegated task.
#
# Runs from the current working directory (intended to be a worktree).
# Exits 0 on pass, non-zero on fail. Prints a structured report.
#
# Checks:
#   1. Python syntax — py_compile every .py in harness/ and tests/
#   2. Imports — key modules import without errors
#   3. Tests — pytest tests/ passes (with timeout)

set -uo pipefail

# Find the repo root (the worktree root — where .git file or .git dir lives)
WORKTREE_ROOT="$(pwd)"
while [ ! -e "$WORKTREE_ROOT/.git" ] && [ "$WORKTREE_ROOT" != "/" ]; do
    WORKTREE_ROOT="$(dirname "$WORKTREE_ROOT")"
done
if [ ! -e "$WORKTREE_ROOT/.git" ]; then
    echo "ERROR: not inside a git worktree" >&2
    exit 2
fi
cd "$WORKTREE_ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

pass() { echo -e "  ${GREEN}PASS${RESET}  $1"; }
fail() { echo -e "  ${RED}FAIL${RESET}  $1"; }
info() { echo -e "  ${YELLOW}--${RESET}    $1"; }

FAILED=0

echo -e "${BOLD}Gate verification — $WORKTREE_ROOT${RESET}"
echo ""

# --- Activate venv if present ---
# Worktrees share the main repo's venv. Derive the main repo root via
# git's common-dir (parent of .git), which resolves to the main checkout
# from inside a linked worktree.
MAIN_REPO_ROOT="$(cd "$WORKTREE_ROOT" && readlink -f "$(dirname "$(git rev-parse --git-common-dir)")")"
if [ -f "$WORKTREE_ROOT/venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source "$WORKTREE_ROOT/venv/bin/activate"
    info "venv activated"
elif [ -f "$MAIN_REPO_ROOT/venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source "$MAIN_REPO_ROOT/venv/bin/activate"
    info "main venv activated (shared from $MAIN_REPO_ROOT)"
else
    info "no venv found, using system python"
fi

# --- Check 1: Python syntax ---
echo ""
echo -e "${BOLD}[1/3] Python syntax check${RESET}"
SYNTAX_ERRORS=0
for dir in harness tests; do
    if [ -d "$dir" ]; then
        while IFS= read -r -d '' f; do
            if ! python -m py_compile "$f" 2>&1 | grep -q .; then
                :
            else
                SYNTAX_ERRORS=$((SYNTAX_ERRORS + 1))
                fail "syntax error: $f"
                python -m py_compile "$f" 2>&1 | sed 's/^/        /'
            fi
        done < <(find "$dir" -name "*.py" -print0 2>/dev/null)
    fi
done
if [ $SYNTAX_ERRORS -eq 0 ]; then
    pass "all .py files compile"
else
    fail "$SYNTAX_ERRORS files have syntax errors"
    FAILED=1
fi

# --- Check 2: Imports ---
echo ""
echo -e "${BOLD}[2/3] Import check${RESET}"
IMPORT_OUT=$(python -c "
import sys
sys.path.insert(0, '$WORKTREE_ROOT')
try:
    from harness import orchestrator, mcp_server, diff_fuzzer, sandbox, ast_enforcer, task_decomposer, cross_examiner
    print('OK')
except Exception as e:
    import traceback
    print('FAIL: ' + str(e))
    traceback.print_exc()
    sys.exit(1)
" 2>&1)
if echo "$IMPORT_OUT" | grep -q "^OK$"; then
    pass "all harness modules import"
else
    fail "import error"
    echo "$IMPORT_OUT" | sed 's/^/        /'
    FAILED=1
fi

# --- Check 3: Tests ---
echo ""
echo -e "${BOLD}[3/3] Test suite${RESET}"
if [ -d "tests" ]; then
    TEST_OUT=$(mktemp)
    if timeout 600 python -m pytest tests/ -q --tb=no --no-header 2>&1 > "$TEST_OUT"; then
        SUMMARY=$(grep -E "passed|failed" "$TEST_OUT" | tail -1)
        pass "tests: $SUMMARY"
    else
        EXIT_CODE=$?
        SUMMARY=$(grep -E "passed|failed|error" "$TEST_OUT" | tail -3)
        if [ $EXIT_CODE -eq 124 ]; then
            fail "tests timed out after 600s"
        else
            fail "tests failed (exit $EXIT_CODE):"
            echo "$SUMMARY" | sed 's/^/        /'
            # Show first failure for context
            grep -A 5 "FAILED\|ERROR" "$TEST_OUT" | head -20 | sed 's/^/        /'
        fi
        FAILED=1
    fi
    rm -f "$TEST_OUT"
else
    info "no tests/ directory"
fi

# --- Summary ---
echo ""
echo "================================================================"
if [ $FAILED -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}GATE PASSED${RESET} — safe to commit"
    echo "================================================================"
    exit 0
else
    echo -e "  ${RED}${BOLD}GATE FAILED${RESET} — do not commit"
    echo "================================================================"
    exit 1
fi
