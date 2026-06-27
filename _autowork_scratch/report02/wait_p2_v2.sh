#!/bin/bash
cd /home/xnihil0zer0/JanusMaskJR
prev=""
for i in $(seq 1 200); do  # up to ~100 min
  st=$(PYTHONPATH=. python -c "
from pathlib import Path
from harness.brief_status import compute_brief_status
for r in compute_brief_status(Path('.'), Path('state')):
    if r.get('slug')=='report02_p2_onesided_oracle':
        print(r['state']+'|acc='+str([a.get('task_id') for a in r['accepted']])+'|blk='+str(r['blocked'])+'|proc='+str(r['processing'])+'|rem='+str(r['remaining']))
" 2>/dev/null)
  [ "$st" != "$prev" ] && { echo "[$(date +%H:%M:%S)] $st"; prev="$st"; }
  echo "$st" | grep -q "^complete" && { echo ">>> P2 COMPLETE"; break; }
  if echo "$st" | grep -q "^blocked" && echo "$st" | grep -q "proc=\[\]" && echo "$st" | grep -q "rem=\[\]"; then echo ">>> P2 TERMINAL-BLOCKED again"; break; fi
  sleep 30
done
echo "WAITER ENDED"
