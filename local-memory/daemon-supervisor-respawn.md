---
name: daemon-supervisor-respawn
description: "autowork daemon is supervised by scripts/run-autowork.sh under systemd --user — kill the child to restart, NEVER nohup a second daemon"
metadata: 
  node_type: memory
  type: project
  originSessionId: f70e0328-8fcd-4b19-80bb-8b82562a11f2
---

The autowork daemon is NOT a bare process: `scripts/run-autowork.sh --state-dir state --logs-dir logs --config harness/config.yaml` (long-lived, parent `systemd --user`) supervises it and RESPAWNS the child within seconds of it dying.

**Why:** discovered 2026-06-11 during the T1 concurrency_isolation restart — handoff said "stop pid X, restart manually"; doing both produced TWO live daemons (double-dispatch hazard). The wrapper had already respawned by the time the manual `nohup` start ran.

**How to apply:** to restart the daemon (e.g. to load freshly-landed harness code past Python's import cache), just `kill -TERM <daemon pid>` and wait ~5s for the wrapper's respawn; verify exactly one pid via `pgrep -af harness.autowork_daemon`. Never start one manually while the wrapper is alive. Daemon stdout goes to `logs/autowork.log`.

Related: [[never-hand-edit-production-outside-pipeline]]
