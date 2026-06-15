---
epic: true
child_epics: true
---

# Title

JanusMaskJR Agent Execution Substrate — subscription-billed interactive backends + isolated
parallelism. Two facts force this epic. (1) Claude Code is about to **bill API tokens for headless
`-p`**, while an *interactive* claude session runs on the operator's Max subscription — so every
overseer/worker turn driven through `claude -p ... --output-format stream-json` becomes a metered
API call we do not want to pay. (2) The runtime is **sequential**, and the moment we run more than
one agent at once they **fight over shared per-process state** (claude's `~/.claude.json`; agy's
`~/.gemini`/`~/.codeium`/`~/.antigravitycli` registry). This epic adds a **`claude-tmux` agent
backend** (drive a persistent *interactive* claude in a tmux pane, read replies from the structured
session transcript — no API billing, no TUI scraping) and a **per-agent isolation discipline**
(claude → `CLAUDE_CONFIG_DIR`; agy → `HOME`) that makes bounded parallelism safe. Concretely it
stands up a **project-local 4-wide agy worker pool** for JanusMask build/research workers, while the
**overseer keeps using the single main system agy install** (and/or the new `claude-tmux` backend).
YOU (the planner) decide the final tree; a non-binding two-pillar grouping is at the end.

# Scope

Add execution **backends** and **isolation**, change no agent's *reasoning* or *authority*. Nothing
about modes, gates, procedures, the build pipeline's logic, or what any agent is allowed to do
changes. We are swapping *how a turn's process is spawned and billed*, and *how concurrent processes
are kept from corrupting each other's on-disk state*. Everything stays behind injected seams so the
deterministic core is JM-rebuildable and oracle-tested with hermetic fakes — no test spawns a real
`claude`/`agy`, touches the network, or makes a model call.

Two independent pillars (decompose each as its own child epic if you prefer):
- **Pillar A — `claude-tmux` interactive backend** (lives in `overseer/`, pure + injected-seam;
  touches NO deny-listed file). Primary consumer: the overseer. Secondary: reusable by any
  claude-driven agent that wants subscription billing.
- **Pillar B — agy worker pool** (the JanusMask *worker* spawn path). A project-local pool of N
  isolated agy homes so up to N build/research workers run concurrently without fighting. The
  overseer is **exempt** — it uses the main system agy install.

# Inputs — ALREADY BUILT; do NOT rebuild. These are DONE seams the new leaves import.

- `overseer/driver.py::run_turn(conversation, user_text, *, runner, env_builder, jail_builder,
  stream_parser, **kw) -> AssistantTurn` and `_build_argv` — the deterministic four-seam shell. It
  already branches on `conversation['agent_backend']` (`'claude'` vs `'agy'`); this epic adds a
  third value `'claude-tmux'`. `AssistantTurn(session_id, text, tool_uses)` is the return contract.
- `overseer/turn_runner.py::make_seams(*, config, repo_root, state_dir, work_dir, timeout)` and
  `run_chat_turn(...)` — builds the REAL four seams (subprocess `runner`, allowlisted `env_builder`,
  `jail_builder` reusing `agent_jail`, `ClaudeStreamParser`). It ALREADY wires the operator's MCP
  servers into every spawn (the mcp-wire epic, `35054e5`): `mcp__<name>` tokens appended to
  `--tools`, host paths bound `extra_ro`/`extra_rw`. `_overseer_work_dir(repo_root, cid)` already
  gives each conversation a private cwd OUTSIDE the repo. `_build_overseer_env` already allowlists
  env (it passes the `CLAUDE_` prefix, so `CLAUDE_CONFIG_DIR` flows through unchanged).
- `overseer/session_store.py` — the per-conversation record already carries `agent_backend` and
  `model`. `overseer/model_select.py` — claude takes `--model`; agy takes none.
- `overseer/transcript.py` — `Turn`/`to_jsonl`/`redact` for the tailed `logs/overseer_chat.jsonl`.
- `harness/agent_jail.py::build_jail_argv(inner, *, repo_root, work_dir, state_dir,
  bind_credentials, extra_ro, extra_rw)` — the bwrap jail. `sandbox_enabled(config)`,
  `bwrap_available()`. A per-agent private HOME or config dir is just another `extra_rw` bind.
- `harness/orchestrator.py` — the worker spawn path. `_is_agy = basename(command)=='agy'`
  (~:429); the agy branch `subprocess.Popen(agy_cmd, ..., cwd=JANUSMASK_WORK_DIR)` (~:447) feeds the
  prompt on STDIN. `harness/autowork_daemon.py` sets `agent_cfg = {'command':
  '${PROJECT_ROOT}/.agents/agy/agy', 'args': ['-p','--sandbox']}` (~:804, ~:2580).

# Verified facts the design rests on (grounded empirically this session — state as rationale, do not re-litigate)

- **Interactive claude bills the subscription, not the API.** A turn driven in a tmux pane shows
  "0 → N tokens" against Claude Max. `--output-format stream-json` is a `--print`-only (headless)
  flag — i.e., the metered path.
- **Interactive claude writes a clean structured transcript** at
  `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/<sanitized-cwd>/<session-uuid>.jsonl`, one record
  per message (`type:"assistant"` with `message.content` text + `tool_use` blocks). The session id
  IS the filename. **So replies are read from JSONL, never scraped from the TUI.**
- **`CLAUDE_CONFIG_DIR` is honored by this build** (v2.1.156) and relocates the WHOLE config tree
  (`.claude.json`, `projects/<cwd>/…` transcripts, history). It is the per-agent isolation knob for
  claude. Subprocess and parent must use the *same* path or transcript-mirror frames drop.
- **Turn-completion is detectable from `capture-pane`**: the pane contains the literal
  `esc to interrupt` while the agent is working and not when idle (an empty `❯` prompt returns).
- **agy is Antigravity** (Google `cortex`/gemini-coder; multi-backend Gemini+Claude+GPT-OSS via
  GCA). Its mutable state is scattered across **home-relative** dirs (`~/.gemini`, `~/.codeium`,
  `~/.antigravitycli`, `~/.cache/antigravity`), so **`HOME` is agy's isolation knob** — relocating
  HOME moves all of it at once. Auth = small home-relative files (`~/.gemini/oauth_creds.json`,
  `google_accounts.json`) + the shared `~/.config/gcloud/application_default_credentials.json`
  (ADC) with `GOOGLE_GENAI_USE_GCA=1`. The 14 GB of `~/.gemini` is regenerable cache — **never
  replicated**; seed only the KB-sized auth/settings set.
- **4 agy processes in 4 seeded private HOMEs ran concurrently with zero conflict** (all rc=0,
  correct answers, ~9 s, no port/auth collision). This is the empirical basis for the pool size.
- The harness already drives agy single-shot via STDIN (`agy -p --sandbox`); agy's native
  *subagent* fan-out is interactive-only and out of scope here.

---

# PILLAR A — the `claude-tmux` interactive backend

## A.1 What a `claude-tmux` turn is (the mechanism)

A conversation whose `agent_backend == 'claude-tmux'` is bound to a **long-lived tmux session**
(named per conversation) running ONE interactive `claude` process in the bwrap jail. A turn is:

1. **Ensure session.** If no live tmux session for this conversation, start one:
   `tmux new-session -d -s <session> -x <cols> -y <rows> -c <work_dir> -- <jailed claude argv>`,
   where the jailed argv is the *interactive* claude (NO `-p`, NO `--output-format`) with the mode's
   `--tools` allowlist + the appended `mcp__*` tokens (reuse the existing jail/MCP wiring), and a
   permission posture that does not dead-end (see A.4). On first start, auto-answer the startup
   dialogs (folder-trust → confirm; bypass-warning if present → accept) by matching the captured
   snapshot and sending the deterministic key sequence.
2. **Send the user turn.** `tmux send-keys -t <session> -- <text>` then `send-keys -t <session>
   Enter`. (Long/multiline text: paste-buffer load + paste to avoid send-keys interpreting control
   tokens.)
3. **Wait for idle.** Poll `tmux capture-pane -t <session> -p` every `poll` seconds; the turn is
   in-flight while the snapshot contains `esc to interrupt`; it is **idle** once that token has been
   absent for K consecutive polls AND the transcript file has stopped growing. Hard `timeout`.
4. **Read the reply from the transcript** (NOT the pane): locate the session JSONL under
   `<config_dir>/projects/<sanitized-cwd>/`, read the records appended since the last marker, fold
   the new `assistant` text + `tool_use` blocks + session id into an `AssistantTurn`.

The real PTY removes the headless permission dead-end — codebase-memory-mcp and other granted MCP
tools that previously had no TTY to approve at now Just Work — so this *also* closes the
brief-author "couldn't reach codebase-memory" friction as a side effect.

## A.2 Per-agent isolation (parallelism-readiness, built in from the start)

Every `claude-tmux` agent owns a tuple **derived from its conversation id**, so the substrate is
N-ready by construction even though the first cut still drives turns one at a time:

```
agent <cid> → tmux session : ovr_<cid>
              cwd           : _overseer_work_dir(repo_root, cid)        # EXISTS
              CLAUDE_CONFIG_DIR : <repo>_agentwork/overseer_cfg/<cid>   # NEW — the isolation key
              state_dir / work_dir : per-cid                            # EXISTS
```

The per-cid `CLAUDE_CONFIG_DIR` is **seeded idempotently** (copy `~/.claude/.credentials.json` +
a minimal config; NOT the operator's history) and bound `extra_rw` into the jail. Because every
per-turn read touches only this agent's own session + own config-dir transcript, fan-out is
embarrassingly parallel: a later pool/scheduler dispatches N turns, each polling its own pane and
reading its own JSONL, with no shared file in the path. **This epic ships the per-agent keying and
seeding; it does NOT ship the scheduler** (that is a later orchestration leaf).

## A.3 Build boundary

Deterministic, JM-rebuildable, pure/stdlib-over-injected-seams: idle detection from a capture
string, startup-dialog detection + key-sequence planning, the JSONL locate/parse/fold, the
config-dir path derivation. The **one real I/O seam** is `tmux_exec(args) -> str` (plus an injected
`sleep`/`clock`); a fake `tmux_exec` returns scripted pane snapshots so oracles drive whole turns
hermetically. The REAL `tmux_exec` (subprocess to the `tmux` binary) and REAL transcript reader are
built where `make_seams` lives.

## A.4 Permission posture (the one real design choice — default B, fail-safe to unchanged)

The interactive TUI shows a folder-trust prompt and, under `--dangerously-skip-permissions`, a
second bypass warning. Posture **B (default, recommended):** seed a project `.claude/settings.json`
allow-list scoped to the mode's tools (+ the `mcp__*` tokens) and run `--permission-mode dontAsk`;
the controller auto-answers only folder-trust. This preserves the "mode = privilege ceiling"
principle *inside* the jail. Posture **A (fallback):** `--dangerously-skip-permissions` + auto-answer
both dialogs, relying solely on the bwrap jail as the containment boundary. The posture is config-
selected; an unknown/absent posture degrades to today's behaviour.

---

# PILLAR B — the agy worker pool (JanusMask workers; overseer EXEMPT)

## B.1 What it is

A project-local pool that lets up to **N (=4)** JanusMask agy *workers* run concurrently without
corrupting each other's registry:

```
.agents/agy-pool/
  agy                  # ONE shared binary (symlink to the real agy); the binary is stateless
  w0/  w1/  w2/  w3/   # one private $HOME per slot, each seeded with ONLY:
    .gemini/{oauth_creds,google_accounts,settings,trustedFolders,state,projects}.json   # ~KB
    .config/gcloud/application_default_credentials.json                                  # ADC
    work/              # the slot's cwd (or the task work_dir is bound in)
```

Worker on slot *i* spawns with `HOME=.agents/agy-pool/w{i}` and `GOOGLE_GENAI_USE_GCA=1`,
everything else unchanged (`agy -p --sandbox`, prompt on STDIN). Each writes its registry/caches
inside its own home → no shared `~/.gemini` to corrupt. Seeding copies only the KB-sized auth set,
**never** the 14 GB cache, and is idempotent (skip if present).

## B.2 The overseer is exempt

The overseer is a single long-lived interactive agent, not a fan-out worker. When it runs on the
**agy** backend it uses the **main system agy install** (`~/.local/bin/agy`, the operator's real
`$HOME`) — no pool slot, no seeded home. (When it runs on the **claude** backend it uses Pillar A's
`claude-tmux`.) Only the orchestrator/daemon *worker* spawn path consults the pool.

## B.3 Build boundary (this pillar straddles two regimes — call it out per leaf)

The **pool home-manager is deterministic and JM-rebuildable** (pure + an injected fs/copy seam):
slot→home path derivation, the pinned seed-file list, idempotent `ensure_seeded`, free-slot
`allocate_slot(busy)->int|None`, `worker_env(slot, base_env)->env`. Tests inject a fake fs; no real
copy, no real spawn. The **spawn-path integration is gated harness code** — editing
`harness/orchestrator.py`'s agy branch and `harness/autowork_daemon.py`'s `agent_cfg` to route a
worker through a pool slot is a `harness_self_fix` change requiring an operator decision file
(`autowork_daemon.py` is on `_NEVER_AUTO_APPROVE`). Keep those edits single-symbol and additive: an
un-pooled spawn (pool disabled / overseer / N=1) must be byte-for-byte today's behaviour.

## B.4 What this pillar does and does NOT deliver

Delivers the **isolation substrate + slot allocation + the gated spawn wiring** so that concurrent
agy workers are *safe*. It does **NOT** itself flip the daemon to dispatch N-wide — actually
enabling concurrent dispatch is a separate scheduler/config decision (and bounded by the GCA
subscription's concurrency/quota ceiling, which N=4 cleared but higher N may not). Ship the safety
primitive; leave the throttle to the operator.

# Correctness regimes (the build boundary, restated)

- **Pure deterministic leaves** (`overseer/tmux_session.py`, `overseer/tmux_transcript.py`, the pool
  home-manager): stdlib-only over INJECTED seams. NEVER spawn a process, call a model/API/network,
  open SSE, or shell out un-injected. All tmux/`claude`/`agy`/fs I/O flows through a single injected
  seam each, so oracles run hermetically with fakes.
- **Additive integration edits** (`overseer/driver.py`, `overseer/turn_runner.py`, the harness
  worker-spawn edits): modify EXISTING symbols ADDITIVELY. With the new backend not selected / pool
  disabled, output and behaviour are byte-for-byte today's. A missing tmux binary, an unreadable
  transcript, an unseeded/absent config-dir or pool home, or any seam error **degrades to today's
  path or an `ok=False` surfaced turn — never raises, never hangs the UI** (the tolerance
  `make_seams` already shows a missing `.claude.json`).
- **Harness regime:** the two worker-spawn edits are `harness_self_fix` + operator decision files.
  Everything else is ordinary `overseer/` (non-deny) territory.

# Per-leaf contract (oracle-first)

Each leaf's `verification_command` MUST name its own pre-committed RED oracle:
`python -m pytest tests/overseer/<oracle>.py -q` (Pillar A) or
`python -m pytest tests/<path>/<oracle>.py -q` (Pillar B substrate). Oracles are hand-authored and
committed RED at HEAD BEFORE any leaf is dispatched (the next gated step after this digestion). NEW
modules are single-file whole-file emissions; INTEGRATION leaves are single-symbol partial edits to
ONE file each — never bundle files. This epic delivers the DECOMPOSITION only — no oracle is
authored and no leaf is built or dispatched here.

# Suggested decomposition (NON-BINDING — you decide the final tree; child epics allowed)

**Pillar A (overseer/, pure + injected-seam):**
- `overseer/tmux_session.py` (NEW, whole-file) → `tests/overseer/test_tmux_session.py`. Session
  controller over ONE injected `tmux_exec` + injected `sleep`: `start_session`,
  `answer_startup_dialogs(snapshot)->keys`, `send_turn`, `wait_idle(*, poll, timeout, settle_k)`,
  `capture`, `kill`. Parameterized by `(session, argv, cwd, env)` — no singletons (N-ready).
- `overseer/tmux_transcript.py` (NEW, whole-file) → `tests/overseer/test_tmux_transcript.py`. Pure
  over an injected reader: `project_dir(config_dir, cwd)`, `session_file(...)`,
  `read_since(path, marker) -> (AssistantTurn, new_marker)` folding assistant text + tool_use +
  session id. Unknown/empty/rotated file → empty turn, no raise.
- EDIT `overseer/driver.py::run_turn` → extend `tests/overseer/test_driver.py`. Add the
  `agent_backend == 'claude-tmux'` path via injected tmux+transcript seams; `'claude'`/`'agy'`
  byte-for-byte unchanged.
- EDIT `overseer/turn_runner.py` → extend `tests/overseer/test_turn_runner.py`. `make_tmux_seams`
  (real `tmux_exec` + real transcript reader) + per-cid `CLAUDE_CONFIG_DIR` seeding + backend
  select from config. Inert with no tmux backend selected.

**Pillar B (worker pool — substrate JM-rebuildable, spawn wiring gated):**
- `harness/agy_pool.py` (NEW, whole-file; operator may relocate out of the deny tree) →
  `tests/harness/test_agy_pool.py`. Pure + injected fs/copy: `pool_root(repo_root)`,
  `worker_home(slot)`, `ensure_seeded(slot, *, src_home, copy_seam)` (idempotent, pinned KB seed
  set, never the cache), `allocate_slot(busy)->int|None`, `worker_env(slot, base_env)->env`
  (`HOME` + `GOOGLE_GENAI_USE_GCA`).
- EDIT `harness/orchestrator.py` (agy branch ~:447) → its oracle. `harness_self_fix` + decision
  file. Route a *worker* agy spawn through an allocated pool slot's `worker_env`; overseer/un-pooled
  path unchanged.
- EDIT `harness/autowork_daemon.py` (`agent_cfg` ~:804/2580) → its oracle. `harness_self_fix` +
  decision file. Make the worker `agent_cfg` pool-aware (command = pooled `agy`, env = slot env);
  default-off ⇒ today's `agy -p --sandbox` exactly.
- EDIT `harness/config.yaml` → config leaf. `overseer.agent_backend` accepting `claude-tmux`; the
  permission posture; `workers.agy_pool` (enabled flag default-OFF, size=4). Safety posture (flags
  OFF) committed FIRST.

# Required plan shape

For the EPIC plan record (this brief): a decomposed leaf tree (one `brief_hooks_<slug>.md` per leaf
at repo root) — or two child epics, one per pillar — plus an epic plan record. For EACH generated
leaf the plan shape is:
- exactly ONE task per leaf (do NOT further split a leaf);
- `files_touched` names the single file that leaf owns;
- `verification_command` = `python -m pytest tests/<dir>/<that leaf's oracle>.py -q`;
- the task `spec.non_goals` MUST contain the literal word "integration";
- `test_spec` MUST carry ≥2 regression_tests reflecting that leaf's edge cases;
- a unique non-`T1` `task_id` with no `state/tasks/processed/<id>` collision;
- integration/harness leaves are single-symbol partial edits (no whole-file rewrite of the edited
  file); harness leaves additionally carry `meta_task_type: harness_self_fix`.

# Edge Cases

- **tmux binary absent / `new-session` fails:** the `claude-tmux` seam reports failure; `run_turn`
  surfaces an `ok=False` turn (never raises). With the backend unselected the path is never entered.
- **Startup dialog variant** (no bypass warning under posture B; or an extra prompt): the dialog
  matcher answers only what it recognizes and otherwise waits-then-times-out, never sends a blind key
  into the input box.
- **Idle false-positive** (model paused mid-turn): require `esc to interrupt` absent for K polls AND
  transcript size stable before declaring idle; cap with a hard timeout.
- **Transcript not yet flushed / rotated / multiple sessions in one cwd:** select the newest session
  file ≥ the start marker; unreadable/empty → empty `AssistantTurn`, turn proceeds.
- **Config-dir / pool home unseeded or unreadable:** seeding is idempotent and best-effort; on
  failure the agent falls back to the un-isolated default path and the turn proceeds (degraded, not
  broken).
- **agy pool exhausted** (all N slots busy): `allocate_slot` returns `None`; the spawn either queues
  or falls back to a single un-pooled spawn — never two workers on one home.
- **Overseer must never take a pool slot:** the worker-spawn edit is reached only on the worker
  path; the overseer's agy spawn uses the main system home unconditionally.
- **Backend not selected / pool disabled:** every integration edit is inert; existing claude/agy/`-p`
  behaviour, rec keys, and tests are preserved exactly.

# Deliverables

A decomposed leaf tree (or two child epics) + an epic plan record covering: Pillar A's deterministic
substrate (`overseer/tmux_session.py`, `overseer/tmux_transcript.py`) and additive integration
(`driver.run_turn`, `turn_runner.make_tmux_seams` + per-cid `CLAUDE_CONFIG_DIR` seeding); Pillar B's
pool home-manager (`harness/agy_pool.py`) and gated spawn wiring (`orchestrator.py`,
`autowork_daemon.py`, `config.yaml`). End state: an overseer (or any claude-driven agent) can run a
multi-turn *interactive* claude session in a tmux pane billed to the Max subscription — replies read
from the structured transcript, MCP working through the real PTY — with per-agent
`CLAUDE_CONFIG_DIR` isolation that makes fan-out safe; and JanusMask agy workers can run up to 4-wide
through a project-local pool of isolated homes without corrupting each other, while the overseer
keeps the single main system agy install. This epic delivers the DECOMPOSITION only; it authors no
oracle and dispatches no build; the owner gate stays paused.

# Non-Goals

- **No scheduler / no flipping on concurrency.** This epic ships the isolation substrate + slot
  allocation; it does NOT make the daemon dispatch N-wide and flips no enable flag (all default-OFF).
- **No change to reasoning, modes, gates, procedures, or the build pipeline's logic** — only how a
  turn's process is spawned/billed and how concurrent processes are isolated.
- **No TUI scraping for reply content** — replies come from the structured transcript JSONL; the
  pane is read only for idle detection and dialog answering.
- **No agy native-subagent orchestration** (interactive-only; separate future work). agy workers
  remain single-shot `-p` STDIN spawns, just pooled.
- **No replication of the 14 GB agy cache or the operator's claude history** — seed only the KB-sized
  auth/credential set; isolation, not cloning.
- **No new MCP-granting logic** — Pillar A reuses the mcp-wire seams (`35054e5`) verbatim.
- **No model-API/network/SSE/un-injected subprocess in any deterministic leaf** — all tmux/claude/
  agy/fs traffic flows through a single injected seam per module.
- Distinct from `brief_hooks_overseer-brief-author-context.md` (phase-aware context provisioning):
  that epic is orthogonal and is NOT folded in here.
```
