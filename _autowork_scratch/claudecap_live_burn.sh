#!/usr/bin/env bash
# Live 4-way claudecap concurrency burn (BOUNDED): stage 4 disjoint claude tasks,
# let the restarted daemon dispatch them, capture the instant 4 claude workers run
# CONCURRENTLY, then tear down immediately to bound OAuth-subscription cost.
set -u
cd /home/xnihil0zer0/JanusMaskJR
ST=state
BURN=_autowork_scratch/claudecap_burn_tasks
mkdir -p "$BURN"

echo "=== 0. ensure paused while we stage (no premature dispatch) ==="
touch "$ST/control/autowork/pause"

echo "=== 1. stage 4 disjoint claude tasks (cloned valid structure, scratch files_touched) ==="
python3 - <<'PY'
import json, pathlib
base = json.load(open('state/tasks/processed/claudecap-daemon-cap.json'))
tdir = pathlib.Path('state/tasks')
for i in range(4):
    t = dict(base)
    tid = f'burn-claude-{i}'
    t['task_id'] = tid
    t['files_touched'] = [f'_autowork_scratch/claudecap_burn_tasks/burn_{i}.py']
    t['dependencies'] = []
    t['priority'] = 'low'
    t['agent'] = 'claude'; t['target_agent'] = 'claude'; t['synthesis_agent'] = 'claude'
    t['verification_command'] = 'python -c "pass"'
    t['spec'] = {'objective': f'Create a one-line module _autowork_scratch/claudecap_burn_tasks/burn_{i}.py defining BURN_MARKER = {i}.',
                 'functional_requirements': [f'module defines BURN_MARKER == {i}']}
    t['test_spec'] = {'unit_tests': [{'name': f'test_burn_{i}'}], 'property_tests': [], 'regression_tests': [{'name':'a'},{'name':'b'}], 'integration_tests': [], 'minimum_test_count': 1, 'edge_cases': []}
    (tdir / f'{tid}.json').write_text(json.dumps(t), encoding='utf-8')
    print('  staged', tid, t['files_touched'])
PY

echo "=== 2. UNPAUSE -> daemon dispatches the 4 staged tasks (allowlist irrelevant for already-staged) ==="
rm -f "$ST/control/autowork/pause"

echo "=== 3. poll for PEAK concurrent claude workers (up to 90s) ==="
peak=0
for i in $(seq 1 45); do
  pf=$(ls "$ST/control/autowork/running/"*.pid 2>/dev/null | wc -l)
  burn_running=$(ls "$ST/control/autowork/running/"burn-claude-*.pid 2>/dev/null | wc -l)
  claude_procs=$(pgrep -fc "tmux_worker|orchestrator_worker.*burn-claude" 2>/dev/null || echo 0)
  [ "$burn_running" -gt "$peak" ] && peak=$burn_running
  echo "  t=$((i*2))s running_pidfiles=$pf burn_workers=$burn_running peak=$peak"
  if [ "$burn_running" -ge 4 ]; then
    echo "  >>> 4 CONCURRENT burn claude workers observed — capturing evidence"
    break
  fi
  sleep 2
done

echo "=== 4. EVIDENCE snapshot ==="
echo "--- running pidfiles ---"; ls -1 "$ST/control/autowork/running/" 2>/dev/null
echo "--- live worker processes (orchestrator_worker for burn tasks) ---"
ps -o pid,ppid,etime,cmd -C python 2>/dev/null | grep -E "orchestrator_worker.*burn-claude" | grep -v grep
echo "--- live claude PTY/tmux processes ---"
ps -o pid,etime,cmd 2>/dev/null | grep -iE "tmux_worker|\.bin/claude" | grep -v grep | head -8
echo "--- ledger: burn launches (parallel branch = 'launch' with NO 'launch_sequential', NO suspend) ---"
grep -E "burn-claude" "$ST/impl_progress.jsonl" 2>/dev/null | python3 -c "
import sys,json
seq=par=0
rows=[]
for l in sys.stdin:
    try: r=json.loads(l)
    except: continue
    e=r.get('event','')
    if e=='launch_sequential': seq+=1
    if e=='launch': par+=1
    if e in ('launch','launch_sequential','worker_start'): rows.append((r.get('ts',''),e,r.get('task_id','')))
for ts,e,t in rows[-12:]: print('   ',ts,e,t)
print(f'  SUMMARY: launch(parallel)={par}  launch_sequential={seq}')
"
echo "PEAK_CONCURRENT_BURN_WORKERS=$peak"

echo "=== 5. TEARDOWN (bound cost): pause, kill burn workers, clean staged/sidecars ==="
touch "$ST/control/autowork/pause"
for p in "$ST/control/autowork/running/"burn-claude-*.pid; do
  [ -e "$p" ] || continue
  pid=$(cat "$p" 2>/dev/null)
  [ -n "$pid" ] && kill -TERM -- "-$pid" 2>/dev/null; kill -TERM "$pid" 2>/dev/null
  echo "  killed worker pid=$pid ($p)"
done
sleep 2
# hard kill any lingering burn workers + their claude children
pkill -9 -f "orchestrator_worker.*burn-claude" 2>/dev/null && echo "  pkilled lingering burn workers"
# clean staged tasks + all burn sidecars
rm -f "$ST/tasks/"burn-claude-*.json "$ST/tasks/"burn-claude-*.json.processing 2>/dev/null
rm -f "$ST/tasks/blocked/"burn-claude-* "$ST/tasks/processed/"burn-claude-* 2>/dev/null
rm -f "$ST/tasks/current_task_"burn-claude-* 2>/dev/null
rm -f "$ST/control/autowork/running/"burn-claude-*.pid 2>/dev/null
rm -f "$ST/output/"burn-claude-* 2>/dev/null
rm -rf "$BURN" 2>/dev/null
rm -f "$ST/tasks/test_results/"burn-claude-* 2>/dev/null
echo "  cleaned burn tasks/sidecars"
echo "=== teardown done; daemon left PAUSED ==="
ls "$ST/tasks/"burn-claude-* 2>/dev/null && echo "WARN: residual burn tasks" || echo "  no residual burn tasks"
