#!/usr/bin/env bash
# Active stall-detector for claudecap. Loops on bounded cadence; EXITS (re-invoking
# the main loop) ONLY on a real signal: TERMINAL (accepted/blocked/exhausted) or
# STALL (no ledger write in >STALE_S AND no live synthesis child). Heartbeats so a
# silent run is impossible. This is the mechanism fix: no-event => still a signal.
cd /home/xnihil0zer0/JanusMaskJR
LEDGER=state/impl_progress.jsonl
STALE_S=600          # 10 min with zero ledger movement = suspect
MAX_LOOPS=80         # ~80 * 30s probe budget cap; bounded, never unbounded
SLEEP_S=30
# SINCE epoch (arg1): only terminal rows with ts > SINCE count (avoids matching
# stale terminal rows already in the ledger). Defaults to launch time.
# slug (arg2): task-slug substring to watch. Defaults to claudecap.
SINCE="${1:-$(date +%s)}"
slug="${2:-claudecap-parallel-isolation}"
for i in $(seq 1 $MAX_LOOPS); do
  now=$(date +%s)
  # terminal events for either claudecap task, NEWER than SINCE only
  term=$(grep -iE "$slug" "$LEDGER" 2>/dev/null | tail -8 | python3 -c "
import sys,json
since=float('$SINCE')
hit=''
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try: r=json.loads(line)
    except: continue
    ts=r.get('ts',0)
    if not isinstance(ts,(int,float)) or ts<=since: continue
    ev=str(r.get('event','')); ph=str(r.get('phase',''))
    if any(k in ev or k in ph for k in ('auto_commit','accepted','reject_rollback','task_blocked','retry_exhausted','verification_failed','planner_validation_rejected')):
        hit=f\"{r.get('ts')} {r.get('task_id','')} {ph}/{ev} {r.get('detail','')[:60]}\"
print(hit)
" 2>/dev/null)
  if [ -n "$term" ]; then echo "TERMINAL@${now}: $term"; exit 0; fi
  last=$(stat -c %Y "$LEDGER" 2>/dev/null || echo 0)
  gap=$((now - last))
  live=$(pgrep -af "$slug" 2>/dev/null | grep -cE 'bwrap|agy|gemini|claude')
  # liveness = a real orchestrator_worker for this slug (synth children can be
  # ORPHANS that falsely look alive — gate stall on worker presence, not them).
  worker=$(pgrep -af "orchestrator_worker.*$slug" 2>/dev/null | head -1)
  if [ "$gap" -gt "$STALE_S" ] && [ -z "$worker" ]; then
    echo "STALL@${now}: ledger idle ${gap}s, NO live worker (synth_children=${live}, may be orphans)"
    exit 0
  fi
  # heartbeat every ~5 min (10 loops)
  if [ $((i % 10)) -eq 0 ]; then
    echo "HEARTBEAT@${now}: i=$i ledger_gap=${gap}s synth_children=${live} worker=${worker:+alive}"
  fi
  sleep $SLEEP_S
done
echo "BUDGET_EXHAUSTED@$(date +%s): ${MAX_LOOPS} loops elapsed, re-probe and re-arm"
