#!/usr/bin/env bash
# (a) which NEW event names actually appear in the live ledger (read-only), and
# (b) what agent-selection-fallback changed in orchestrator (hypothesis 5).
set -u
cd /home/xnihil0zer0/JanusMaskJR
LED=state/impl_progress.jsonl
echo "=== distinct event names present in the LIVE ledger (read-only grep) ==="
if [ -f "$LED" ]; then
  grep -oE '"event": *"[a-z_]+"' "$LED" | sed -E 's/.*"event": *"([a-z_]+)".*/\1/' | sort | uniq -c | sort -rn | head -40
else
  echo "(no live ledger file)"
fi
echo
echo "=== do the NEW wire-up events appear live yet? ==="
for ev in wireup_symbol_verdict orphan_symbol_unwired orphan_unwired inactivity_watchdog_triggered daemon_source_changed; do
  n=$(grep -c "\"event\": \"$ev\"" "$LED" 2>/dev/null || echo 0)
  echo "  $ev : $n live rows"
done
echo
echo "=== agent-selection-fallback diff (orchestrator) — what changed? ==="
git log --oneline e5c0f9fb..HEAD -- harness/orchestrator.py | grep -i fallback
echo "--- the fallback commit's actual hunk (agent selection) ---"
git show e2f1051 --stat 2>/dev/null | head -8
echo
echo "=== grep current orchestrator for the fallback selection logic ==="
grep -n "claude_fallback\|_fallback\|fallback_agent\|verify.fallback\|unavailable\|agent.*fallback\|_select_agent\|active_agents" harness/orchestrator.py | head -20
