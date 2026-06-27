#!/bin/bash
cd /home/xnihil0zer0/JanusMaskJR
prev=""
for i in $(seq 1 80); do   # ~40 min at 30s
  snap=$(PYTHONPATH=. python -c "
from pathlib import Path
from harness.brief_status import compute_brief_status
out=[]
for r in compute_brief_status(Path('.'), Path('state')):
    s=r.get('slug','')
    if s.startswith('report02'):
        out.append(f\"{s}:{r['state']} acc={r['accepted']} blk={r['blocked']} q={r['queued']} proc={r['processing']}\")
print(' || '.join(out))
" 2>/dev/null)
  if [ "$snap" != "$prev" ]; then
    echo "[$(date +%H:%M:%S)] $snap"
    prev="$snap"
  fi
  # stop early if both leaves are fully accepted or blocked
  echo "$snap" | grep -q "report02_p1_dict_synth:complete" && echo "$snap" | grep -q "report02_p2_onesided_oracle:complete" && { echo "BOTH COMPLETE"; break; }
  sleep 30
done
echo "POLL LOOP ENDED"
