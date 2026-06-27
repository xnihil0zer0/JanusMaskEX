---
name: factory-backend-headless-cutover-2026-06-23
description: Factory workers.claude_backend flipped tmux→headless (-p) on 2026-06-23 (commit b47e8ad) per owner directive; daemon restarted (pid 692097) reads headless + idle clean. Records WHY prior -p switches never stuck and the durable config-knob rule.
metadata:
  node_type: memory
  type: project
  originSessionId: abc9547b-8d8a-4bd6-b44d-ee0591b3fcfc
---

🔁 UPDATE 2026-06-25 (CURRENT): backend is **headless** again (commit **25660f7**), reverting
fa9f44d which had flipped it to **tmux** on a FALSE premise. fa9f44d claimed "`-p` seeds a
creds-less CLAUDE_CONFIG_DIR the CLI can't OAuth from → claude produced no draft since 06-23, ~2
days gemini-only." BOTH halves DISPROVEN empirically: (1) `claude -p` (v2.1.193) authenticates via
OAuth with **NO** ANTHROPIC_API_KEY and returns output (live test → "PONG", exit 0); `-p` is fully
supported + OAuth-capable (no changelog removal — confirmed via docs). The owner-relayed claim "`-p`
needs an API key now / no longer works with OAuth" is FALSE. (2) the ledger shows **190** claude
`agent_status=submitted` rows DURING the headless window 06-23 20:57…06-25 20:20 (right up to 19min
before the flip), with recent `single_agent_promotion` rows dropping **gemini** and keeping claude —
the opposite of "gemini-only." Claude drafts fine under headless. Daemon restarted 154267→**158434**
(21:04) reads headless. ⚠️ The c33f808 `_seed_claude_config_dir` empty-dir worry is NOT
blocking in practice (190 drafts prove OAuth resolves under headless); do not re-flip on it. If a
durable per-task config-dir seed is ever wanted, mirror `overseer/tmux_seams.seed_config_dir` (copies
`.credentials.json`/`settings.json`/`.claude.json`) — but it is not currently needed.

✅ PRIOR STATE (2026-06-23): `workers.claude_backend: headless` (commit **b47e8ad**, operator
config cutover, master-direct — mirrors the e1f5aab tmux flip). Daemon restarted via the kill rule
(680922 → **692097**); the fresh daemon read `headless` at startup and reached idle cleanly. Routes
claude factory workers through the headless `-p`/print path (`_build_agent_command` + `--settings
config/claude_worker_hooks.json` + `_assert_claude_hook_config`), which RE-REGISTERS the claude
`pre_tool` tool-allowlist hook that the tmux/PTY seam (`overseer/tmux_seams.py`) does NOT install.
⚠️ Hook re-registration is DETERMINISTIC FROM CODE but NOT yet runtime-observed (allowlist deny-all,
no worker dispatched since the flip) — confirm on the next real task or a queued validation brief.

💸 BILLING FLIPS: tmux/PTY = OAuth/Max **subscription**-billed; headless `-p` = **API**-billed
(metered). At ~30–70 worker runs/day this is a real cost change. ⚖️ TRADE-OFF: headless loses the
`--continue` warm-resume optimization (`resume_pinned_session` fires only on the tmux path) → AST-retries
cold-start. To REVERT: flip `claude_backend` back to `tmux` + restart → restores the jailed-interactive
PTY backend + warm resume (and drops the pre_tool hook again).

📜 BACKGROUND (7-agent transcript audit 2026-06-23): backend was `tmux` CONTINUOUSLY from 2026-06-14
(e1f5aab, "owner directive: tmux-jailed-claude default everywhere, not headless -p") until b47e8ad.
The owner stated intent to be on `-p` on 2026-06-22 (verbatim: *"I switched from tmux to -p for claude"*)
and again 2026-06-23, but it NEVER LANDED — git shows the value never changed off tmux until b47e8ad,
working tree was clean. (`git log -S 'claude_backend'` does NOT detect a value-only flip; use
`-G'claude_backend:'` or `-L`.) NOTE the Jun-14 decision sessions are MISSING from the transcript
corpus (files jump Jun13→Jun15→Jun17), so the "owner directive" is recorded in commit msgs + memory,
not quoted from a user turn.

★★ DURABLE RULE — WHY HAND-EDITS DON'T STICK: `harness/config.yaml` is pipeline-managed and the daemon
reads it ONLY at startup (config knobs are NOT in the self-reload watch set). So an uncommitted hand-edit
to a knob (a) never reaches the running daemon without a restart, and (b) is at risk of being clobbered
by the pipeline's own `config.yaml` auto-commits (which branch from committed HEAD — tmux). TO CHANGE A
CONFIG KNOB: edit + **COMMIT** + **restart the daemon** (`kill -TERM $(cat state/control/autowork.pid)`,
supervisor run-autowork.sh respawns), OR route via pipeline. Leading (unproven) hypothesis for the
owner's lost switches = exactly this clobber/no-restart gap.
[[never-hand-edit-production-outside-pipeline]] [[daemon-self-reload-landed]] [[daemon-supervisor-respawn]]
[[watchdog-stall-brief-queued-and-daemon-denylist]]
