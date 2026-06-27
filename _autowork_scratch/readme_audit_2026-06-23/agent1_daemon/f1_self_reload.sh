#!/usr/bin/env bash
# Finding 1: daemon self-reload — prove it exists + condition (idle + sha change).
set -euo pipefail
cd /home/xnihil0zer0/JanusMaskJR
echo "=== _should_reload_daemon signature + idle/sha condition ==="
sed -n '1363,1421p' harness/autowork_daemon.py | grep -nE "def _should_reload_daemon|_pause_flag_path|_has_active_rebuild_job|running.*pid|current != startup_sha|return current"
echo
echo "=== run_daemon: startup sha captured ONCE + per-iteration check + clean exit ==="
grep -nE "startup_sha = _daemon_source_sha|_new_sha = _should_reload_daemon|daemon_source_changed|return 0" harness/autowork_daemon.py
echo
echo "=== commit that introduced it ==="
git log --oneline e5c0f9fb..HEAD -- harness/autowork_daemon.py | grep -iE "self-reload|self_reload" || echo "(see 98e5fd1 daemon-self-reload-impl)"
