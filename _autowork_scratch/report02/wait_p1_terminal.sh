#!/bin/bash
cd /home/xnihil0zer0/JanusMaskJR
for i in $(seq 1 120); do  # up to ~60 min
  st=$(PYTHONPATH=. python -c "
from pathlib import Path
from harness.brief_status import compute_brief_status
for r in compute_brief_status(Path('.'), Path('state')):
    if r.get('slug')=='report02_p1_dict_synth':
        print(r['state'], '| acc=', r['accepted'], '| blk=', r['blocked'], '| remaining=', r['remaining'])
" 2>/dev/null)
  echo "[$(date +%H:%M:%S)] P1: $st"
  case "$st" in
    complete*) echo ">>> P1 COMPLETE"; break;;
  esac
  # if blocked with no remaining queued, surface it
  echo "$st" | grep -qE "blocked.*remaining= \[\]" && { echo ">>> P1 appears blocked/terminal"; }
  sleep 30
done
