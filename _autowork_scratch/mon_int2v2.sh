#!/usr/bin/env bash
cd /home/xnihil0zer0/JanusMaskJR
LOG=_autowork_scratch/mon_int2v2.log
: > "$LOG"
for i in $(seq 1 240); do
  TS=$(date +%H:%M:%S)
  # recent impl_progress lines for our v2 ids
  PROG=$(grep -h 'int2-onesided-metamorphic-v2' state/impl_progress.jsonl 2>/dev/null | tail -4)
  PROC=$(ls state/tasks/processed/ 2>/dev/null | grep 'int2-onesided-metamorphic-v2' | tr '\n' ' ')
  BLOCK=$(find state/control/autowork/selfheal_skip -iname '*int2*metamorphic*v2*' 2>/dev/null | tr '\n' ' ')
  PLAN=$(ls state/plans/ 2>/dev/null | grep -i 'int2.*metamorphic.*v2' | tr '\n' ' ')
  echo "[$TS i=$i] processed=[$PROC] blocked=[$BLOCK] plan=[$PLAN]" >> "$LOG"
  [ -n "$PROG" ] && echo "  progress: $PROG" >> "$LOG"
  # exit early if both processed
  echo "$PROC" | grep -q 'v2-impl' && echo "$PROC" | grep -q 'v2-oracle' && { echo "[$TS] BOTH PROCESSED" >> "$LOG"; break; }
  sleep 30
done
echo "MONITOR DONE" >> "$LOG"
