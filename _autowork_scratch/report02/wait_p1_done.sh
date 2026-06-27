#!/bin/bash
cd /home/xnihil0zer0/JanusMaskJR
for i in $(seq 1 160); do  # up to ~80 min
  st=$(PYTHONPATH=. python -c "
from pathlib import Path
from harness.brief_status import compute_brief_status
for r in compute_brief_status(Path('.'), Path('state')):
    if r.get('slug')=='report02_p1_dict_synth':
        print(r['state']+'|acc='+str(r['accepted'])+'|blk='+str(r['blocked'])+'|proc='+str(r['processing'])+'|rem='+str(r['remaining']))
" 2>/dev/null)
  echo "[$(date +%H:%M:%S)] $st"
  echo "$st" | grep -q "^complete" && { echo ">>> P1 COMPLETE"; break; }
  # terminal-blocked: state blocked and nothing remaining/processing
  if echo "$st" | grep -q "^blocked" && echo "$st" | grep -q "proc=\[\]" && echo "$st" | grep -q "rem=\[\]"; then echo ">>> P1 TERMINAL-BLOCKED"; break; fi
  sleep 30
done
