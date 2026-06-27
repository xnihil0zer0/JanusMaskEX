#!/usr/bin/env bash
# _phase2_run_child.sh <plan_hooks.json> <tid1> [<tid2> ...]
# Stage each task from the plan, then dispatch in the given (dependency) order
# via impl_dispatch_once.sh. Reports commit outcome per task.
set -u
cd /home/xnihil0zer0/AI-Data/JanusMaskEX
PLAN="$1"; shift
echo "=== staging tasks from $PLAN ==="
for tid in "$@"; do
  python3 - "$PLAN" "$tid" <<'PY'
import sys, pathlib
from harness.planner.staging import stage_task
plan, tid = sys.argv[1], sys.argv[2]
try:
    stage_task(pathlib.Path(plan), tid, pathlib.Path('state'), canonical=True)
    print(f"  staged {tid}")
except FileExistsError:
    print(f"  already staged {tid}")
except Exception as e:
    print(f"  STAGE ERR {tid}: {type(e).__name__}: {e}")
PY
done
echo
for tid in "$@"; do
  echo "=== dispatching $tid ==="
  bash scripts/impl_dispatch_once.sh "$tid" state 1500 2>&1 | tail -8
  echo "--- post-dispatch: ledger outcome for $tid ---"
  grep "\"$tid\"" state/impl_progress.jsonl 2>/dev/null | tail -2
  echo
done
echo "=== git log (last 6) ==="
git log --oneline -6
echo "=== harness/symbol_ledger.py present? ==="
ls -la harness/symbol_ledger.py 2>/dev/null || echo "(NOT created)"
