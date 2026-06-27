#!/usr/bin/env bash
# Bounded claudecap terminal monitor — handles BOTH epoch-float and ISO-string ts
# (the known detector bug). Exits on first terminal row for either claudecap task
# newer than SINCE, or on stall (no worker + ledger idle), or budget exhaustion.
cd /home/xnihil0zer0/JanusMaskJR
LEDGER=state/impl_progress.jsonl
SINCE="${1:-$(date +%s)}"
MAX=100; SLEEP=30; STALE=900
for i in $(seq 1 $MAX); do
  now=$(date +%s)
  hit=$(grep -iE 'claudecap-parallel-isolation' "$LEDGER" 2>/dev/null | tail -25 | SINCE="$SINCE" python3 -c "
import sys,os,json,datetime
since=float(os.environ['SINCE'])
def toepoch(ts):
    if isinstance(ts,(int,float)): return float(ts)
    if isinstance(ts,str):
        try: return datetime.datetime.strptime(ts,'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc).timestamp()
        except: return 0.0
    return 0.0
out=''
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try: r=json.loads(line)
    except: continue
    if toepoch(r.get('ts'))<=since: continue
    ev=str(r.get('event','')); ph=str(r.get('phase',''))
    if any(k in ev for k in ('auto_commit','task_blocked','retry_exhausted','verification_failed','reject_rollback','planner_validation_rejected','orphan_unwired')):
        out=f\"{r.get('ts')} {r.get('task_id','')} {ph}/{ev} :: {str(r.get('detail',r.get('outcome','')))[:70]}\"
print(out)
" 2>/dev/null)
  if [ -n "$hit" ]; then echo "TERMINAL@${now}: $hit"; exit 0; fi
  last=$(stat -c %Y "$LEDGER" 2>/dev/null || echo 0); gap=$((now-last))
  worker=$(ls state/control/autowork/running/*claudecap* 2>/dev/null | head -1)
  if [ "$gap" -gt "$STALE" ] && [ -z "$worker" ]; then
    echo "STALL@${now}: ledger idle ${gap}s, no claudecap worker pidfile"; exit 0
  fi
  if [ $((i % 6)) -eq 0 ]; then echo "HEARTBEAT@${now}: i=$i gap=${gap}s worker=${worker:+alive}"; fi
  sleep $SLEEP
done
echo "BUDGET_EXHAUSTED@$(date +%s): ${MAX} loops"
