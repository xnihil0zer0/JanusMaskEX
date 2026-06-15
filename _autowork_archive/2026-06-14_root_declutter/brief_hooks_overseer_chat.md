---
epic: true
child_epics: true
---

# Title

JanusMaskJR Overseer Chat — add an interactive, multi-turn overseer agent to the WebUI that
functions like Claude Code / agy, but whose MODE selects which hook/inbox/outbox state machine
the agent is constrained to. The agent self-selects among available modes; some modes are
user-unlocked. This is a deliberately LARGE, self-modifying epic; YOU (the planner) decide how to
decompose it into a multi-level tree.

# Scope

Today the WebUI (the LIVE one is the stdlib `tools/webui_server.py` + `tools/webui_static/app.js`
SPA — the `webui/` Flask tree is a DEAD abandoned port; do NOT build there) has NO interactive
agent. Every agent spawn is one-shot: build `-p <prompt>`, jail it, poll `outbox/` for a single
file-drop, kill it. The closest analog is the autobrief flow (`tools/webui_control.py:
post_brief_autocomplete` + `_parse_autobrief_stdout`), which is blocking and discards streaming
deltas.

This epic adds a CHAT PANEL backed by a NEW interactive driver and a MODE SYSTEM. The mode system
is an operator-facing generalization of three things the harness ALREADY does: (a) `JANUSMASK_MODE`
(synthesis|planning|reconciliation) already drives a synchronized inbox-staging / session-entry-gate
/ outbox-write-gate triple (`harness/orchestrator.py:4225`, `harness/hooks/_env.py:31`,
`harness/hooks/claude/pre_tool.py:143`); (b) `harness/mcp_server.py:build_execute_tool(mode)` already
returns a DIFFERENT command enum per mode — a jailed agent literally cannot call a tool outside its
mode; (c) the trust gradient is already encoded in five mechanisms (pause/full_stop flags, decision
files, the auto-promote allowlist, `_SENSITIVE_APPLY_GLOBS`, and the irreducible
`orchestrator._NEVER_AUTO_APPROVE` deny-list). An overseer "mode" is just a named pinning of
(agent tool/route allowlist + permitted procedures + apply authority) over those existing seams.
The cardinal project rule the modes must encode and never violate: NEVER hand-edit production
outside the pipeline.

Two correctness regimes define the build boundary, exactly as in prior epics. DETERMINISTIC logic
(pure functions, local stateful stores, and shells around an INJECTED non-deterministic dependency)
is IN — JM gates it with oracle + fuzz/smoke. The non-deterministic LIVE work is OUT, made an
injected seam: the actual subprocess spawn of `claude`/`agy`, the real model API call, and the live
SSE socket write are all injected callables in the tested surface, so the factory never spawns a
real agent. The driver is a deterministic shell around an injected `runner` seam (the
`ngv2.poc_runner` / `ngv2.semgrep_adapter` pattern applied to agent spawning).

# Architecture & design constraints (read before decomposing — these shape the tree)

1. **All NEW logic goes in a NEW repo-root package `overseer/`** (NOT under `harness/`). `overseer/**`
   is NOT matched by `_SENSITIVE_APPLY_GLOBS` (`harness/** config/** scripts/** services/**`), so each
   new `overseer/*.py` module is a single-file, whole-file, auto-committable build — the proven-reliable
   pipeline path (identical to how the `ngv2/` package built hands-off). It MAY import harness internals
   by module path (`from harness.agent_jail import build_jail_argv`, etc.); importing is free, editing is
   not.
2. **The driver MUST NOT edit any `_NEVER_AUTO_APPROVE` file** (`orchestrator.py`, `agent_jail.py`,
   `git_integration.py`, `autowork_daemon.py`, `selfheal.py`, `dbus_proxy.py`, `paths.py`,
   `interceptors.py`, `services/**`). These can NEVER be auto-approved even under `harness_self_fix`.
   The driver therefore REUSES the jail/env/stream primitives BY IMPORT — `agent_jail.build_jail_argv`,
   `orchestrator._build_agent_env`, `agent_streamer.ClaudeStreamParser` — and builds its own argv. Model
   selection is done in the NEW driver's own argv assembly (NOT by editing `orchestrator._build_agent_command`).
3. **Multi-turn continuity = claude-code `--resume <session_id>`.** Each turn is a fresh
   `-p --resume <sid> --model <m> --output-format stream-json --include-partial-messages` spawn that
   resumes the prior session (claude-code persists session state under `~/.claude/projects/...`, already
   rw-bound inside the jail). The driver captures the new session_id from the stream-init event and
   stores it. agy has NO `--model` flag (it is a compiled Antigravity/Gemini binary that self-selects a
   tiered model) and is driven via STDIN like today's agy path — so the model dropdown applies to claude
   only; agy is offered as a backend with no model pick.
4. **Edits to existing files are the ONLY sensitive/fragile leaves** and must be kept THIN (wiring only):
   `tools/webui_control.py` + `tools/webui_server.py` (meta_task_type `harness_plumbing`; `tools/**` is
   NOT in the deny-list), `tools/webui_static/{app.js,index.html,styles.css}` (frontend), and
   `harness/config.yaml` (meta_task_type `harness_self_fix` + an operator decision file at apply time —
   `config.yaml` is sensitive but NOT in `_NEVER_AUTO_APPROVE`). Prefer adding NEW top-level
   functions/methods over modifying existing method bodies (the never-patch-class-methods rule); register
   handlers via the documented dispatch-table seam.
5. **Frontend clobber guard:** `boot()` re-renders all of `#page` on every SSE tick, which would wipe the
   chat input + transcript (the known `briefEditorIsOpen()` bug, `app.js:1136`/`:1209`). The chat panel
   MUST add a `chatIsOpen()` predicate to the re-render skip guard AND self-manage its DOM (append-only
   transcript element + persistent input), never relying on full-page re-render.
6. **Modes are enforced by WITHHOLDING tools, not by prompt** (the `mcp_server` precedent). The driver
   passes the mode's concrete tool/route allowlist to the spawned agent; the agent cannot exceed it. The
   irreducible backstops (`_enforce_apply_scope`, `_NEVER_AUTO_APPROVE`, pause/full_stop, the allowlist)
   remain authoritative regardless of mode.
7. **Default posture is fail-safe:** ship with `overseer.enabled: false`; boot every conversation in the
   read-only `observe` mode; Tier-S modes are user-unlock-only and never self-selected; `full_stop` is
   never auto-cleared; `flag-steward` defaults toward deny-all; no mode may broaden `_NEVER_AUTO_APPROVE`.
8. **Resend / step-back must be PROMPT-CACHE-FRIENDLY.** claude-code prompt caching is a PREFIX cache (an
   unchanged leading run of tokens hits cache at ~10%; only the new tail is full price; the cache is warm
   only within its TTL, default ~5 min). Two operations are supported and BOTH preserve cache: (a) APPEND a
   turn (continue forward — whole prior transcript is an unchanged prefix); (b) REWIND to an earlier turn N,
   DISCARD turns after N, then continue (prefix up to N is still byte-identical). EDITING a turn in the
   middle while keeping later turns is NOT a supported cache-preserving operation (it invalidates the cache
   from the edit point on) — if the user edits an earlier turn, treat it as a rewind+branch from that point,
   not an in-place edit of a kept tail. The driver MUST reconstruct the resent prefix VERBATIM (byte-identical
   to what was cached — same message text, no paraphrase/re-wrap) so the prefix actually hits cache; use
   claude-code `--resume <sid>` to append and `--fork-session` to branch a rewind into a new session id.
   (Caching reasoning is claude-only; the agy backend has separate cache/quota semantics. On OAuth the win is
   reduced usage-limit accounting, not a dollar price.)

# Your decomposition task

Decompose this epic into a MULTI-LEVEL tree of your own design (lineage depth up to 4: root -> ...
-> leaf). YOU decide the structure, the intermediate epic levels, and the grouping. Mark every
non-leaf brief `epic: true` (and `child_epics: true` when its children are themselves epics). Give
every child a kebab-case slug; NO non-leaf slug may equal any leaf slug.

Each NEW-FILE leaf is one NEW single-file, whole-file, stdlib-only (or injected-seam) Python module
under the `overseer/` package, IMPL-ONLY (it must NOT author tests — its contract is the RED oracle
committed before dispatch at `tests/overseer/test_<leaf>.py`, delivered via oracle-injection),
verified with `python -m pytest tests/overseer/test_<leaf>.py -q`. Reproduce each module name and its
public surface EXACTLY as the committed oracle pins them (the suggested surfaces below are what the
oracle will fix). Each EDIT leaf modifies one existing file with the THIN wiring described, carries
the meta_task_type noted, and is pinned by its own committed oracle. Prefer leaves that are
independent; the only intra-set ordering is that `mode_gate`/`mode_prompts`/`actions`/`driver`/
`web_api` build on `modes` (definitions) and `session_store`/`transcript` (state), so order those
foundations first — and the final adversarial UI-fidelity sweep (§H) is ordered strictly LAST, after the
whole panel is built and wired.

# The body of work — capabilities to build

Grouped below ONLY for readability; regroup, split, or merge as you judge best.

## A. Mode-system core (NEW files under `overseer/`, pure)

- `overseer/modes.py` [pure] — the mode registry. A `ModeSpec` dataclass and `MODE_REGISTRY` dict
  defining ALL 14 modes (see §"The 14 modes" below), each carrying: `name`, `tier` (`R`|`W`|`S`),
  `janusmask_mode` (synthesis|planning|reconciliation|none), `allowed_tools` (subset of
  Read/Glob/Grep/Write/Bash/MCP/...), `allowed_routes` (WebUI GET/POST/PUT route patterns),
  `allowed_meta_task_types`, `inbox_contract`, `outbox_contract`, `apply_authority`, `default_available`,
  `requires_unlock`, `fallback_mode`. Plus pure helpers `get_mode(name)`, `list_available_modes(unlocked)`,
  `requires_unlock(name)`. (oracle `tests/overseer/test_modes.py`)
- `overseer/mode_gate.py` [pure] — mode enforcement (the tool-withholding resolver, mirroring
  `mcp_server.build_execute_tool`). `assert_tool_allowed(mode, tool)`, `assert_route_allowed(mode, method,
  path)`, `can_switch(current, target, unlocked) -> bool`, `resolve_tool_allowlist(mode) -> list[str]`
  (the concrete `--tools`/route set the driver hands the agent). Raises a typed `ModeViolation` on deny.
  (oracle `tests/overseer/test_mode_gate.py`)
- `overseer/mode_prompts.py` [pure] — per-mode procedure guidance. `MODE_PROMPTS` (the system-prompt /
  procedure text per mode) and `render_mode_context(mode, state) -> str` (the SessionStart
  `additionalContext` analog: "you are in mode=X, tier=Y, you may do A/B/C, you may NOT do D"). (oracle
  `tests/overseer/test_mode_prompts.py`)

## B. Conversation / session layer (NEW files under `overseer/`)

- `overseer/transcript.py` [pure] — `Turn`/`Message` dataclasses, append-only model, `to_jsonl`/`from_jsonl`,
  and a `redact(text)` that strips operator-secret-shaped tokens before persistence/echo. Each `Turn` carries
  `role` (user|assistant) AND the `mode` it was produced under (so the UI can render a per-turn color-coded
  mode label) plus a monotonic `index`. Provides `reconstruct_prefix(turns, up_to_index) -> list[Message]`
  that rebuilds the message list VERBATIM up to a given turn (the cache-friendly prefix used by resend/rewind
  — see constraint 8); it must reproduce the exact original text, never re-wrap or re-summarize. (oracle
  `tests/overseer/test_transcript.py`)
- `overseer/session_store.py` [stateful, injected path seam] — a deterministic store mapping a
  conversation id to `{claude_session_id, current_mode, unlocked_modes, model, agent_backend,
  transcript}`. SQLite-or-JSON backed via an EXPLICIT `store_path` seam (no real on-disk default in the
  tested surface). `create(...)`, `get(cid)`, `append_turn(cid, turn)`, `set_mode(cid, mode)`,
  `unlock_mode(cid, mode)`, `set_model(cid, model)`, `set_session_id(cid, sid)`. (oracle
  `tests/overseer/test_session_store.py`)

## C. Interactive driver (NEW files under `overseer/`, injected-seam — touches NO deny-listed file)

- `overseer/model_select.py` [pure] — `AVAILABLE_MODELS` (`claude` -> opus|sonnet|haiku; `agy` -> internal,
  no pick) and `resolve_model_argv(agent, requested) -> list[str]` (claude -> `["--model", m]`; agy -> `[]`),
  with validation that rejects an unknown model. (oracle `tests/overseer/test_model_select.py`)
- `overseer/driver.py` [injected-seam] — the per-turn loop. `run_turn(conversation, user_text, *, runner,
  env_builder, jail_builder, stream_parser) -> AssistantTurn`. Builds the claude argv
  (`-p --resume <sid> --model <m> --output-format stream-json --include-partial-messages --tools <mode
  allowlist>`) or the agy STDIN path; wraps via the INJECTED `jail_builder` (defaults to
  `agent_jail.build_jail_argv`) and `env_builder` (defaults to `orchestrator._build_agent_env`); spawns via
  the INJECTED `runner` seam (NEVER spawns a real process in tests); parses streamed deltas via the
  injected `stream_parser` (defaults to `agent_streamer.ClaudeStreamParser`); extracts and returns the new
  session_id + accumulated assistant text + tool-use events. The mode's tool allowlist comes from
  `mode_gate.resolve_tool_allowlist`. Writes streamed deltas to `logs/overseer_chat.jsonl` (the SSE relay
  source) via an injected sink. Supports cache-friendly resend/rewind (constraint 8): given a
  `rewind_to_index` (or none = plain append), it reconstructs the VERBATIM prefix via
  `transcript.reconstruct_prefix`, uses `--resume <sid>` to append or `--fork-session` to branch a rewind into
  a fresh session id (returned so the store can track the branch), and NEVER does an in-place mid-edit. The
  resent prefix must be byte-identical so it actually hits the prefix cache. (oracle
  `tests/overseer/test_driver.py`)

## D. Action surface — the 14 modes' procedures (NEW file under `overseer/`, injected-seam)

- `overseer/actions.py` [injected-seam] — the mode-gated action dispatcher that wires each Tier-W/Tier-S
  mode to the EXISTING operator action via INJECTED callables, so the tested surface has zero side effects.
  `dispatch_action(mode, command, args, *, seams) -> dict`, enforcing `mode_gate` authority first, then
  routing: brief-author -> autobrief/persist seam; oracle-author -> test-staging seam; dispatch ->
  stage_task+worker seam; triage -> selfheal-harvest seam; daemon-supervisor -> lifecycle seam (pause
  always allowed; start/resume gated); ui-tester -> playwright-drive + ground-truth-read seam (live UI
  mutations only through the same gated endpoints; no code write); flag-steward -> config/allowlist-write seam
  (defaults toward deny-all; never broadens `_NEVER_AUTO_APPROVE`); harness-self-fix -> pipeline+decision-file seam;
  security-review -> read+verdict seam (no writes); rebuild-factory -> rebuild-start seam; push ->
  full-gate+git-push seam (refuses on red suite / regressions over baseline). Read-only modes
  (observe/analyze/audit) resolve to GET/read seams. (oracle `tests/overseer/test_actions.py`)

## E. WebUI backend (NEW file + THIN edits to `tools/`)

- `overseer/web_api.py` [injected-seam] — the JSON handler functions, operating on injected
  `session_store` + `driver` + `actions` seams: `chat_send(body)` (start a turn, return
  `{conversation_id, job_id}`), `chat_history(cid)`, `mode_get(cid)`, `mode_set(cid, mode)` (rejects an
  unlock-required target unless unlocked; reverts to fallback on error), `mode_unlock(cid, mode)`
  (records the per-action user unlock), `model_list()`, and `chat_resend(cid, *, rewind_to_index=None)` (the
  resend-transcript / step-back button — replays via the driver's cache-friendly path; `None` resends the
  whole transcript, an index branches/rewinds from that turn). Returns plain JSON-able dicts. (oracle
  `tests/overseer/test_web_api.py`)
- `tools/webui_control.py` [EDIT, meta_task_type `harness_plumbing`] — register the overseer handlers in
  the `_dispatch_post`/`_dispatch_get`/`_dispatch_put` tables and add thin handler methods that delegate to
  `overseer.web_api` (reuse `_spawn_tracked` for the driver subprocess; auth/CSRF come free via
  `_dispatch_mutation`). THIN wiring only; add NEW methods, do not rewrite existing method bodies. (oracle
  `tests/overseer/test_webui_control_overseer.py`)
- `tools/webui_server.py` [EDIT, meta_task_type `harness_plumbing`] — add `logs/overseer_chat.jsonl` to the
  `build_tailer` fixed-paths set so the driver's streamed deltas relay to the browser over the existing
  `/events` SSE channel (clients filter by conversation/job id). (oracle
  `tests/overseer/test_webui_server_tailer.py`)

## F. WebUI frontend (EDITs to `tools/webui_static/`)

- `tools/webui_static/app.js` [EDIT, frontend] — add `pages.chat` (transcript element + persistent input +
  mode selector + model dropdown + per-mode unlock affordance), wire a `startSSE` branch that routes
  overseer-chat tail lines into the transcript by conversation id, and ADD `chatIsOpen()` to the re-render skip
  guard so SSE ticks never clobber the panel. Self-manage the chat DOM (append-only transcript, persistent
  input). Required UX:
  - **Selectable / copyable / editable text everywhere.** Each transcript turn renders as a discrete,
    user-selectable block whose raw text can be selected and copied (a per-block copy affordance plus normal
    text selection — do NOT trap selection or re-render over it); and an EDITABLE affordance on a turn (editing
    a turn is a cache-friendly REWIND+branch from that turn via `chat_resend(cid, rewind_to_index=N)`, never an
    in-place mid-edit — per constraint 8). The input field is a normal editable textarea supporting
    select/copy/paste/edit; it is never wiped by an SSE tick (that's what the `chatIsOpen()` guard + persistent
    DOM ensure).
  - **Per-turn color-coded mode label.** Each turn shows a small label of the `mode` it was produced under
    (carried on the `Turn`, §B `transcript.py`), color-coded by mode (consistently, e.g. grouped by tier —
    Tier R / W / S families share a hue ramp). The color map is a single source of truth in `styles.css`.
  - **Resend-transcript button.** A control that calls `chat_resend(cid)` (resend whole transcript) — and the
    per-turn edit/rewind affordance reuses the same endpoint with a `rewind_to_index`. The UI should hint when
    a resend is likely a cache miss (e.g. transcript idle past the ~5-min TTL) but never block it.
  (oracle — a DOM/JS test or structural assertion per the project's frontend-test convention;
  `tests/overseer/test_chat_ui.*`)
- `tools/webui_static/index.html` + `styles.css` [EDIT, frontend] — add the `#/chat` nav link and panel
  styling, including the single-source-of-truth per-mode color map for the turn labels and styles for the
  selectable/copyable transcript blocks, edit/rewind affordance, and resend button. (covered by the chat-ui
  oracle)

## G. Configuration (EDIT to `harness/config.yaml`)

- `harness/config.yaml` [EDIT, meta_task_type `harness_self_fix` + operator decision file] — add an
  `overseer:` block: `enabled: false` (default-off), `default_mode: observe`, `default_backend: claude`,
  `models: {claude: [opus, sonnet, haiku]}`, `store_path`, `unlock_policy` (which Tier-S modes need
  per-action vs session unlock). (oracle `tests/overseer/test_config_overseer.py`)

## H. Adversarial UI-fidelity sweep + bug-fix loop (FINAL phase — runs AFTER A–G are built and green)

This phase is a VERIFICATION + REMEDIATION harness, not a deterministic single-file leaf: it drives the
LIVE loopback WebUI through a real browser (Playwright) and adversarially checks that everything the UI
displays faithfully reflects ground-truth project state AS THAT STATE UPDATES — then drives a fix for every
discrepancy. It is ordered LAST and depends on the whole panel being wired (the chat panel, the SSE relay,
the mode/model controls). It is intrinsically LIVE/non-deterministic, so it does NOT build under the
deterministic oracle+fuzz gates the way the `overseer/` leaves do — frame it like the project's existing
adversarial-sweep workflows (a planner orchestrating Playwright runs), and route every fix back THROUGH the
pipeline (never hand-edit production). This phase is the ONE-TIME, end-of-build execution of what the
`ui-tester` mode (§"The 14 modes" #9) does as a standing capability — they share the same Playwright harness
and ground-truth-vs-DOM checks.

- `tests/overseer/ui_fidelity/` [Playwright harness, hand-authored — `test_authoring` lane] — a
  Playwright (via the playwright MCP / a vendored playwright) test suite, loopback-only, that:
  - Establishes GROUND TRUTH independently of the UI by reading the same sources the server reads — the GET
    API (`/api/state`, `/api/briefs/status`, `/api/tasks/*`, `/api/autowork/status`, `/api/planner/*`), the
    `state/**` JSONL ledgers, and git — then asserts the rendered DOM matches it (brief statuses, task queue
    counts, daemon/autowork pills, planner/job state).
  - **Adversarially exercises LIVE UPDATE fidelity:** mutate state through real endpoints (stage a task,
    append an `impl_progress.jsonl` row, pause/resume in a sandbox, post a chat turn) and assert the UI
    CONVERGES to the new truth within the SSE/poll window (bounded wait, NOT fixed sleeps); assert it does
    NOT show stale/lagging/duplicated data after a burst of SSE ticks.
  - **Targets the NEW chat panel specifically:** transcript fidelity vs `session_store` (every turn present,
    in order, verbatim — no clobber); each turn's COLOR-CODED MODE LABEL matches the mode actually recorded
    for that turn (labels can't desync from the store); the model dropdown reflects/`set`s the conversation
    model; the resend-transcript and per-turn rewind/edit affordances produce the right transcript (a
    rewound/discarded turn disappears; a branch starts from the chosen turn); the `chatIsOpen()` guard
    actually protects the input + transcript from SSE-tick clobber; mode-unlock gating is reflected in the UI
    (a locked Tier-S mode is not selectable without unlock).
  - **Adversarial intent:** actively try to BREAK the invariant "UI == project state" — race a render against
    a state burst, switch routes mid-update, edit an input while ticks arrive, drive rapid mode/model
    switches — and flag any divergence.
- Bug-fix remediation [pipeline] — every discrepancy the sweep finds becomes (a) a deterministic RED oracle
  reproducing it where the root cause is in `overseer/**` or `tools/**` logic (then fixed via the normal
  pipeline: `harness_plumbing` for `tools/**`, standard gates for `overseer/**`, `harness_self_fix`+decision
  for any sensitive file), and (b) a committed Playwright regression test under `tests/overseer/ui_fidelity/`
  for purely live/timing issues. The phase is DONE when the sweep is green and the suite has 0 new
  regressions vs baseline. NO hand-edits to production — fixes route through briefs/plans.

# The 14 modes (the full set — each realized as a `MODE_REGISTRY` entry + `actions` route + `mode_prompts`)

Tier R (read-only, auto-granted, agent self-selects freely):
1. `observe` — situation room over the WebUI GET surface; DEFAULT boot + fallback mode; no writes.
2. `analyze` — codebase cartographer; codebase-memory-mcp graph + Read/Grep/Glob; no writes.
3. `audit` — ledger/diff/fuzz inspector; read-only over `state/` + read-only git; no commit.

Tier W (action via pipeline; default-available but gated by existing flags):
4. `brief-author` — NL request -> validated `brief_hooks_*.md`/`plan_hooks_*.json` (autobrief flow); writes
   only brief/plan files at root; authoring a brief is NOT dispatching it.
5. `oracle-author` — hand-author RED oracles under `tests/**` only (the ONE sanctioned hand-edit lane);
   meta_task_type `test_authoring`; no production writes.
6. `dispatch` — stage_task -> worker; inert unless the slug is in the auto-promote allowlist; commits only
   through the worker's scoped auto-commit.
7. `triage` — self-heal: diagnose a blocked task and emit a `_fix.md` keyed on the ORIGINAL task_id
   (HMAC-provenance gated); promotion gated by `selfheal_auto_promote`.
8. `daemon-supervisor` — autowork/orchestrator lifecycle; pause/stop auto-granted (fail-safe direction);
   start/resume require unlock; may NOT clear `full_stop`.
9. `ui-tester` — Playwright UI-fidelity tester (the STANDING-mode counterpart to the one-time §H sweep).
   Drives the LIVE loopback WebUI through a real browser (the playwright MCP / vendored playwright) to verify
   that what the UI displays faithfully tracks project state AS IT UPDATES, then hands any bug off for a
   pipeline fix. Establishes ground truth INDEPENDENTLY of the UI (GET API + `state/**` ledgers + git) and
   asserts the DOM matches and converges on live updates (bounded wait, not sleeps). To exercise live-update
   fidelity it MAY drive the bounded set of state mutations the sweep needs (stage a task, append a ledger
   row, pause/resume, post a chat turn) — but ONLY through the same real gated endpoints, so every backstop
   (pause/`full_stop`, the allowlist, decision files, unlock requirements) still applies; clicking a Tier-S
   control in the UI grants nothing the backend wouldn't already gate. Writes NO production code itself —
   remediation routes through `oracle-author` (a deterministic RED oracle or a committed Playwright regression
   test under `tests/overseer/ui_fidelity/`) + `brief-author`/`dispatch`/`harness-self-fix`. Default-available;
   prefers a scratch/sandbox state and loopback-only.

Tier S (security-gated, user-unlock ONLY, never self-selected):
10. `flag-steward` — flip `config.yaml` autowork/control flags + edit the auto-promote allowlist; defaults
    toward deny-all; per-flip owner confirmation to enable any auto-approve flag; never broadens
    `_NEVER_AUTO_APPROVE`.
11. `harness-self-fix` — the ONLY path to change protected production (`harness/** config/** scripts/**`)
    via pipeline + decision file; bound by `_NEVER_AUTO_APPROVE` defense-in-depth.
12. `security-review` — read-only pre-flip auditor; precondition to flag-steward/harness-self-fix; emits a
    go/no-go verdict, writes nothing.
13. `rebuild-factory` — drive external-target (NobleGreedv2) builds via the rebuild routes; commits only to
    the target repo, never JM's.
14. `push` — full serial-suite gate (0-new-regression vs baseline) -> `git push`; refuses on red suite;
    never force-pushes; explicit human sign-off only.

# Mode-switching semantics (encode in `mode_gate`)

The agent may move freely among Tier-R modes and DOWN the privilege lattice at any time, announcing the
switch. R->W is permitted for default-available W modes (but the EFFECT stays gated by existing flags — a
`dispatch` under a deny-all allowlist does nothing). Entering ANY Tier-S mode requires an explicit per-action
user unlock recorded in the session. A mode is the privilege CEILING, enforced by withholding tools. On
ambiguity, error, or an expired unlock, revert to `observe`.

# Suggested decomposition (non-binding starting point)

One reasonable shape: a super-epic per lettered group above (A mode-core, B session, C driver, D actions,
E backend, F frontend, G config, H UI-fidelity sweep), with the foundation super-epics (A, B) ordered before
the ones that depend on them (C/D/E), frontend/config after that, and the H adversarial sweep LAST (it
depends on the entire panel being built and wired — it is the final verification+remediation phase, not a
parallel leaf). The 14 modes are DATA inside `modes.py` + routes inside `actions.py`, not separate leaves.
Adopt, adapt, or reject this — decide on cohesion, leaf independence, dependency order, and a balanced tree.
Whatever you choose, every NEW-FILE module and every EDIT leaf listed above must appear exactly once as a
leaf, and the H phase must be ordered strictly after all of A–G.

# Preconditions (before this epic is dispatched)

Per the house rule that ONLY oracles/tests may be hand-authored, and "commit oracle before run": a RED
oracle for EACH leaf above must be hand-authored and committed at its `tests/overseer/test_<leaf>.py` path
BEFORE dispatch (the daemon cannot author these — interface mismatch). Each new-file leaf is then built
IMPL-only against its committed oracle via oracle-injection. The suggested public surfaces above are what
those oracles will pin; if an oracle pins a different name, the oracle is authoritative. Also confirm before
dispatch: the auto-promote allowlist admits this epic's slug (transitive child admission), the gate is
un-paused, and operator decision files are pre-staged for the sensitive EDIT leaves (`harness/config.yaml`).

# Non-Goals

No live agent spawn, real model API call, or real SSE socket write in any TESTED path (all injected seams).
No editing of any `_NEVER_AUTO_APPROVE` file (`orchestrator.py`, `agent_jail.py`, `git_integration.py`,
`autowork_daemon.py`, `selfheal.py`, `dbus_proxy.py`, `paths.py`, `interceptors.py`, `services/**`) — the
driver reuses them by import. No work in the DEAD `webui/` Flask tree. No `--model` knob for agy (it
self-selects). No new network-exposed surface (the WebUI stays loopback-only). No auto-clearing of
`full_stop`; no mode that broadens `_NEVER_AUTO_APPROVE`; no enabling any auto-approve flag by default
(`overseer.enabled: false` ships off). No agent self-selection into a Tier-S mode. No third-party imports
(stdlib only; injected seams for any external dependency, including the agent subprocess).

# Inputs

The JanusMaskJR repo itself (self-build; no external `working_dir`). Reusable existing primitives (imported,
NOT edited): `harness/agent_jail.py:build_jail_argv`, `harness/orchestrator.py:_build_agent_env`,
`harness/agent_streamer.py:ClaudeStreamParser`/`GeminiStreamParser`, the autobrief flow in
`tools/webui_control.py:post_brief_autocomplete`/`_parse_autobrief_stdout`, the dispatch tables at
`tools/webui_control.py:116-117`, the SSE machinery at `tools/webui_server.py:51-205,708-779`, the SPA
router at `tools/webui_static/app.js`, the mode-gating precedent at `harness/mcp_server.py:44`, the
per-mode inbox/outbox seams at `harness/orchestrator.py:4225` + `harness/hooks/_env.py:31` +
`harness/hooks/claude/pre_tool.py:143`, and the trust gradient (`harness/control_gate.py`,
`harness/git_integration.py:16,44`, `harness/orchestrator.py:2174`, the auto-promote allowlist). Per-leaf
contracts are the committed `tests/overseer/test_<leaf>.py` oracles; only the committed oracle is
authoritative for a build.

# Required plan shape

- Each NEW-FILE leaf: meta_task_type by location — `overseer/**` modules are NOT sensitive, so the standard
  synthesis/fuzz/smoke gates apply; build as ONE single-file whole-file module; a brand-new top-level symbol
  rides as a trailing node via an `implementation_notes` R-anchor hint. Verification command targets ONLY
  that leaf's `tests/overseer/test_<leaf>.py` (do NOT glob the whole `tests/overseer/` dir; do NOT pre-stage
  sibling oracles).
- `tools/webui_control.py` and `tools/webui_server.py` EDIT leaves: meta_task_type `harness_plumbing`; ADD
  new functions/methods and register via the dispatch-table seam — do NOT modify existing method bodies
  (never-patch-class-methods); keep the diff thin.
- `tests/**` (oracle-author) leaves: meta_task_type `test_authoring` (hand-authored as a precondition, not
  daemon-built).
- `harness/config.yaml` EDIT leaf: meta_task_type `harness_self_fix` + an operator decision file at
  `state/control/decisions/<task_id>.json` (config.yaml is sensitive but not in `_NEVER_AUTO_APPROVE`).
- Frontend EDIT leaves (`app.js`/`index.html`/`styles.css`): additive; app.js MUST add `chatIsOpen()` to the
  re-render skip guard.
- §H adversarial UI-fidelity sweep: ordered LAST (after all of A–G). The Playwright suite is hand-authored
  (`test_authoring` lane), runs against the LIVE loopback server (it is NOT a deterministic oracle+fuzz leaf —
  treat it like the project's adversarial-sweep workflows, a planner orchestrating live browser runs). Every
  bug it finds is fixed THROUGH the pipeline (a deterministic RED oracle + the appropriate meta_task_type fix,
  or a committed Playwright regression test for live/timing-only issues) — never a hand-edit. Phase DONE = sweep
  green + 0 new regressions vs baseline.

# Deliverables

A new `overseer/` package (`modes`, `mode_gate`, `mode_prompts`, `transcript`, `session_store`,
`model_select`, `driver`, `actions`, `web_api`) of single-file, whole-file, oracle-pinned modules; the thin
wiring edits to `tools/webui_control.py`, `tools/webui_server.py`, `tools/webui_static/{app.js,index.html,
styles.css}`; the `overseer:` block in `harness/config.yaml` (default-off); each leaf verified GREEN with
`python -m pytest tests/overseer/test_<leaf>.py -q`, organized under the multi-level epic hierarchy YOU
decompose. Plus, as the FINAL phase, a hand-authored Playwright UI-fidelity sweep (`tests/overseer/ui_fidelity/`)
that has run green against the live loopback WebUI — proving the UI (including the new chat panel, its
color-coded per-turn mode labels, and resend/rewind controls) faithfully tracks project state as it updates —
with every bug it surfaced fixed through the pipeline and 0 new regressions vs baseline. End state: a
default-off, loopback-only chat panel where an overseer agent (claude with a model dropdown, or agy) holds a
multi-turn conversation via `--resume`, self-selects among Tier-R/W modes, and is constrained — by
tool-withholding over the existing hook/inbox/outbox seams — to the fixed class of
procedures each mode permits, with Tier-S modes reachable only by explicit user unlock.
