# Codex CLI Wiring Proposal (surgical, additive)

Owner-cleared hand-edits: `harness/config.yaml` + `harness/orchestrator.py`.
Codex binary: `~/.nvm/versions/node/v22.17.0/bin/codex` (`@openai/codex@0.133.0`).

## 1. How claude & gemini are configured today

`harness/config.yaml` top-level `agents:` block (lines 3-39). Each agent = `{command, args[]}`:
- **claude** (L9-29): real Claude CLI, `command: ${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude`, args include `-p`, `--model opus`, `--output-format stream-json`, `--verbose`, `--settings ${CONFIG_DIR}/claude_worker.json`, `--mcp-config ...`, `--tools Read,Glob,Grep,Write`. Streamed Popen, writes outbox via Write tool.
- **gemini** (L35-39): `command: ${PROJECT_ROOT}/.agents/agy/agy`, args `-p --dangerously-skip-permissions`. Basename `agy` -> agentic STDIN path.
- **claude_fallback** / **antigravity**: also `agy`-backed.

Active set: `synthesis.active_agents: [claude, gemini]` (L103-105).
Worker-config refs: `config/claude_worker.json` (rewired at runtime to `_hooks.json`), `config/gemini_worker_policy.toml`. There is NO codex worker config file and none is required (codex needs no JM hook settings).

Note: `webui_config_schema.py:89` already declares a `codex` ProviderSpec (`'codex': ProviderSpec('codex','Codex (CLI)','',False)`) — so the name is reserved; only orchestrator dispatch + config agents entry are missing.

## 2. Orchestrator dispatch seam (name -> subprocess)

- **`_build_agent_command(agent, prompt, config)`** `orchestrator.py:162-193`: pure config-driven. Reads `config['agents'][agent]['command']` + `['args']`, applies hook-config rewire, inserts `prompt` right after the `-p` token (else appends `-p prompt`). Returns argv. **No hardcoded agent names except the claude `--permission-mode` special-case (L178).** A new agent works here for free once it has a config entry.
- **`spawn_agent(agent, prompt, config, round_number)`** `orchestrator.py:377-533`: builds env, builds cmd, jails it, then branches:
  - `_is_agy = basename(command) == 'agy'` (**L459**) -> STDIN agentic path (L460-520): strips `-p <prompt>`, appends a no-file-write tail, `proc.communicate(input=stdin_prompt)`, `_extract_python_block(out)` (test_author.py:150), writes `outbox/submission.py`. Synchronous; returns exited proc.
  - else (claude) -> streamed detached Popen (L521-533).
- **`poll_for_submission`** `orchestrator.py:1025-1146`: agent-agnostic; promotes `outbox/submission.py` via `_path_b_outbox_fallback` (L1074) regardless of agent. So the agy outbox-write path is exactly what makes a non-Write agent submittable.
- **`run_agent_phase`** `orchestrator.py:1148-1169`: agent-agnostic spawn->poll->kill.
- **`run_both_agents`** `orchestrator.py:1171-1235`: reads `synthesis.active_agents`, takes `agent_a=[0]`, `agent_b=[1]`. **Assumes exactly TWO slots** (a/b). claude_fallback special-cases are keyed on literal `'claude'` name (L1188,1196,1219,1226) and harmlessly skip for codex.

**Conclusion:** Agents are config-driven, NOT hardcoded to {claude,gemini}. A third agent kind plugs in by (a) a `config.yaml` agents entry and (b) one branch in `spawn_agent` to handle codex's agentic CLI (it does not have a JM Write tool, so it needs the outbox-extraction path, same shape as agy).

## 3. Codex CLI headless contract (verified via --help)

Non-interactive subcommand: **`codex exec`** (alias `e`). Verified flags:
- Prompt: positional `[PROMPT]`, or read from **stdin** if omitted / `-` (stdin appended as `<stdin>` block if both given). -> mirror agy: pass prompt over stdin.
- Model: `-m, --model <MODEL>`.
- Headless / no prompts: `-s, --sandbox <read-only|workspace-write|danger-full-access>` and `-a, --ask-for-approval never`. For fully non-interactive automation inside the JM bwrap jail, use `--dangerously-bypass-approvals-and-sandbox` (codex is ALREADY externally sandboxed by JM's bwrap jail, exactly the documented use case: "Intended solely for running in environments that are externally sandboxed").
- Working dir: `-C, --cd <DIR>`.
- Machine-readable: `--json` (JSONL events to stdout) OR `-o, --output-last-message <FILE>` (final agent message to a file). `--output-schema <FILE>` for structured final.
- Other useful: `--skip-git-repo-check`, `--ephemeral` (no session files), `--ignore-user-config`, `--color never`.

**Chosen invocation (simplest, matches agy extraction):** let codex emit a fenced ```python block on stdout, parse with `_extract_python_block`. Prompt via stdin (so `_build_agent_command` inserts no positional prompt — strip `-p` like agy does).

```
codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --color never -m gpt-5-codex
```
(prompt piped on stdin; the existing agy no-write tail asks for one fenced ```python block.)

## 4. Proposed minimal wiring

### (a) `harness/config.yaml` — add codex to the `agents:` block

INSERT after the `claude_fallback:` entry (alphabetical, between `claude_fallback` L30-34 and `gemini` L35), or anywhere in the `agents:` map:

```yaml
  codex:
    command: /home/xnihil0zer0/.nvm/versions/node/v22.17.0/bin/codex
    args:
    - exec
    - --dangerously-bypass-approvals-and-sandbox
    - --skip-git-repo-check
    - --color
    - never
    - -m
    - gpt-5-codex
    - -p
    - ''
```
Notes:
- Trailing `-p ''` placeholder: `_build_agent_command` finds `-p` and inserts the prompt after it; the agentic branch (below) then STRIPS `-p <prompt>` and routes the prompt over stdin — identical to how agy is handled. If you prefer no placeholder, omit the `-p` lines and the build path appends `-p prompt` (still stripped by the codex branch). Keep `-p ''` for symmetry with agy.
- `command` uses an absolute path; `${PROJECT_ROOT}`-style vars are only for repo-vendored bins. If a var like `${CODEX_BIN}` is later introduced, swap it here.
- Default model `gpt-5-codex` is a placeholder — set to the owner's licensed codex model. `-m` is overridable per-role (see (c)).

To make codex actually run as a synthesis slot, also (optionally) edit:
```yaml
synthesis:
  active_agents:
  - claude
  - codex      # was: gemini  (or keep gemini and see (c) re: 2-slot limit)
```

### (b) `harness/orchestrator.py` — one-line generalization of the agentic branch

The agy STDIN/outbox path is exactly what codex needs (agentic CLI, no JM Write tool, emits fenced python). Generalize the `_is_agy` predicate to also match codex.

BEFORE (`orchestrator.py:459`):
```python
    _is_agy = os.path.basename(config['agents'][agent]['command']) == 'agy'
    if _is_agy:
```
AFTER:
```python
    _agentic_basename = os.path.basename(config['agents'][agent]['command'])
    _is_agy = _agentic_basename in ('agy', 'codex')
    if _is_agy:
```
Rationale: inside the branch the only command-specific assumption is "strip `-p <prompt>`, feed prompt on stdin, parse one fenced ```python block, write outbox/submission.py" (L462-515) — all true for `codex exec` with stdin prompt + the existing no-write tail. The `try: del agy_cmd[_p_index:_p_index+2]` (L466-469) already tolerates a missing `-p`. No other change in the branch is needed.

Optional clarity-only rename (NOT required): leave `_is_agy` name as-is to keep the diff to two lines.

That is the COMPLETE production diff: 1 config entry + 1 two-line predicate change.

### (c) Drop-in third option? 2-slot assumption + role routing

- `run_both_agents` (L1171-1235) is hard-wired to exactly two slots (`agent_a`, `agent_b`). Codex is NOT a simultaneous THIRD parallel agent without refactoring that function. The supported, zero-refactor way to use codex today: put it IN `active_agents` as slot a or b (replacing gemini, or as a 2-agent {claude, codex} panel). It then dispatches through the generalized agentic branch with no further change.
- A true 3-way panel would require widening `run_both_agents` to iterate `active_agents` (a separate, larger change) — out of scope for "minimal".
- **Role-based model selection:** there is currently no role->agent map in config for synthesis (only `overseer.models` exists, claude-only, L120-123). Model selection for codex is via the `-m` arg in its `agents.codex.args`. To assign codex to a specific role with a specific model, the minimal lever is to set `-m <model>` in the config entry; finer per-role routing depends on the not-yet-built model_backends layer (see (d)).

### (d) Coupling to harness/model_backends.py / agent_block() / CodexCliBackend

- **`harness/model_backends.py` DOES NOT EXIST** (confirmed: `ls` -> No such file). No `agent_block()` or `CodexCliBackend` anywhere in `harness/` (only unrelated `agent_block_ids` in git_integration.py).
- The only codex-aware code that exists is `webui_config_schema.py:89` (a static ProviderSpec for the webui dropdown) — it does NOT drive orchestrator dispatch.
- **Codex CAN be wired fully independently of model_backends.py.** The proposal above touches only config.yaml + the spawn_agent predicate; it has ZERO dependency on the unbuilt backend module. When model_backends.py / CodexCliBackend later lands, it can supersede the inline agentic branch, but is not a prerequisite.

## Risk / verification notes
- bwrap jail still wraps codex (L420-446) before the agentic branch; `--dangerously-bypass-approvals-and-sandbox` is correct precisely because JM's jail is the real sandbox.
- `_assert_claude_hook_config` (L408) is claude-only; codex skips it.
- claude_fallback special-cases (L1188 etc.) key on literal `'claude'`; they do not fire for codex (correct — codex has no agy fallback wired; if desired, add codex->claude_fallback later).
- Verify the chosen default `-m` model id is valid for the owner's codex auth before first live run (`codex exec -m <model> "print hi"` smoke test).
- Confirm codex, given the no-write tail, reliably emits a single fenced ```python block on stdout; if it instead writes files or returns prose, switch to `-o, --output-last-message <FILE>` + read that file in the branch (small follow-up).
