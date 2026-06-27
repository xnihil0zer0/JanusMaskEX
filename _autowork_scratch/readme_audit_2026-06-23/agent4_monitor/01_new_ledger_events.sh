#!/usr/bin/env bash
# Find every NEW ledger event string introduced since the README baseline (e5c0f9fb)
# in my owned files. Read-only.
set -u
cd /home/xnihil0zer0/JanusMaskJR
echo "=== event strings emitted in CURRENT orchestrator.py / wire_up.py / state_reconciler.py / brief_status.py ==="
grep -rnoE "'event'[[:space:]]*:[[:space:]]*'[a-z_]+'" harness/orchestrator.py harness/wire_up.py harness/state_reconciler.py harness/brief_status.py 2>/dev/null \
  | sed -E "s/.*:'event'[^']*'([a-z_]+)'.*/\1/" | sort -u
echo
echo "=== \"event\": \"...\" double-quote form ==="
grep -rnoE '"event"[[:space:]]*:[[:space:]]*"[a-z_]+"' harness/orchestrator.py harness/wire_up.py harness/state_reconciler.py harness/brief_status.py 2>/dev/null \
  | sed -E 's/.*"event"[^"]*"([a-z_]+)".*/\1/' | sort -u
echo
echo "=== which of these event strings are NEW vs the README baseline file content? ==="
for ev in wireup_symbol_verdict orphan_symbol_unwired orphan_unwired stall_detected stall_healed would_be_orphan inactivity_watchdog_triggered detonation static_reachability; do
  base=$(git show e5c0f9fb:harness/orchestrator.py 2>/dev/null | grep -c "'$ev'\|\"$ev\"")
  cur=$(grep -rc "'$ev'\|\"$ev\"" harness/orchestrator.py harness/wire_up.py harness/state_reconciler.py 2>/dev/null | awk -F: '{s+=$2} END{print s}')
  echo "event=$ev  baseline_orch_hits=$base  current_total_hits=$cur"
done
echo
echo "=== where is wireup_symbol_verdict emitted (file:line) ==="
grep -rn "wireup_symbol_verdict" harness/*.py | grep -iE "write_jsonl_row|'event'" | head
echo
echo "=== where is orphan_symbol_unwired emitted ==="
grep -rn "orphan_symbol_unwired" harness/orchestrator.py | head
