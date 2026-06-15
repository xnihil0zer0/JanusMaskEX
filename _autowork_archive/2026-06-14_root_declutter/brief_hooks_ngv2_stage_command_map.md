---
working_dir: /home/xnihil0zer0/NobleGreedv2
interfaces: "exposes `command_for_phase(phase: str, session_ctx: dict) -> dict` — pure/deterministic; runnable spec for agent phases, fail-closed {runnable: False, reason} otherwise; never mutates session_ctx; no subprocess/I/O"
---

# Title

NobleGreed deterministic phase→command-spec mapper (ngv2/stage_command_map.py)

# Scope

Build the NEW whole-file module `ngv2/stage_command_map.py` exposing the pure, stdlib-only function `command_for_phase(phase: str, session_ctx: dict) -> dict`. NobleGreed's bug-hunt state machine walks the phases source→hunt→triage→verify→poc→detonate→novelty→report→awaiting_submission→submitted→done; the owner is automating the machine so deterministic SCRIPTS sit between agent stages. This module deterministically maps a phase to the COMMAND SPEC used to spawn that phase's agent worker — so no agent decides which driver to launch. It only BUILDS the spec; it does NOT spawn, fork, exec, read, write, sleep, or touch the network/clock/randomness.

Logic (deterministic, fail-closed): the seven agent-driven phases {hunt, triage, verify, poc, detonate, novelty, report} each map to a stable argv `["python", "-m", "ngv2.workers." + phase, "--session-id", session_id, "--repo", repo, "--target", target_path, "--out", output_path]` where `output_path = f"{output_dir}/{phase}.json"`, and `env` is `{"NGV2_SESSION_ID": session_id}` merged over a COPY of `session_ctx.get("env", {})` (or an empty dict) — the input `session_ctx` is never mutated. A successful agent phase returns `{"runnable": True, "phase": phase, "argv": list[str], "output_path": str, "env": dict}`. The non-agent/terminal phases {awaiting_submission, submitted, done} (human/terminal — no agent) and any unknown phase return `{"runnable": False, "phase": phase, "reason": str}`. Missing/empty `session_id` or `output_dir` in `session_ctx` for an otherwise-agent phase returns `{"runnable": False, "phase": phase, "reason": str}` (fail-closed). meta_task_type=`validation`. verification_command: `python -m pytest tests/ngv2/test_stage_command_map_wired.py -q`.

Required plan shape: ONE whole-file impl task; meta_task_type=`validation`; files_touched=`["ngv2/stage_command_map.py"]`; >=5 edge_cases mirrored in the pre-committed oracle (see Deliverables). The module is reachable/wired by the conductor spawn path that asks it which driver to launch per phase; the pre-committed wiring oracle `tests/ngv2/test_stage_command_map_wired.py` imports `command_for_phase` from the live `ngv2.stage_command_map` module and proves the contract.

# Non-Goals

This module does NOT spawn, fork, exec, or subprocess anything; it only builds the spec. It does NOT perform any filesystem, network, clock, or randomness I/O, and contains no `eval`/`exec`. It does NOT mutate the input `session_ctx` (env is built on a copy). It does NOT author new tests (the oracle is pre-committed). It does NOT touch any `harness/**`, `config/**`, `scripts/**`, `services/**`, or `_NEVER_AUTO_APPROVE` file. No integration test is required for this pure, single-file validation module — the deterministic spec builder is exercised entirely by its unit/wiring oracle, and end-to-end integration with a real conductor spawn loop is explicitly out of scope for this leaf.

# Inputs

Fixed inputs (reuse, do not reimplement): the NobleGreed phase ordering source→hunt→triage→verify→poc→detonate→novelty→report→awaiting_submission→submitted→done is the canonical phase vocabulary; the `session_ctx` dict carries `session_id` (str), `repo` (str), `target_path` (str), `output_dir` (str), `model` (str, optional), and an optional `env` (dict). The pre-committed RED oracle `tests/ngv2/test_stage_command_map_wired.py` IS the authoritative contract: it imports `command_for_phase` from `ngv2.stage_command_map` (the wiring assertion) and asserts every edge case below. The PRE-COMMITTED RED-oracle convention follows the shape of `tests/ngv2/test_poc_authenticity_gate_wired.py`.

# Deliverables

NEW whole-file `ngv2/stage_command_map.py`. Exposes exactly:

`command_for_phase(phase: str, session_ctx: dict) -> dict`

Return shapes:
- Agent phase, valid ctx: `{"runnable": True, "phase": phase, "argv": list[str], "output_path": str, "env": dict}`.
- Non-agent/terminal/unknown phase, or missing `session_id`/`output_dir`: `{"runnable": False, "phase": phase, "reason": str}`.

Edge cases (all mirrored in the pre-committed oracle, must turn it GREEN):
- (a) `phase="poc"` with full ctx → `runnable is True`, `output_path` endswith `"poc.json"`, `argv` contains `"--session-id"` and the literal `session_id` value, and `argv` contains `"-m"` and `"ngv2.workers.poc"`.
- (b) `phase="awaiting_submission"` → `runnable is False` (human/terminal phase, no agent), with a `reason`.
- (c) unknown `phase="foo"` → `runnable is False`, with a `reason`.
- (d) ctx missing `session_id` (e.g. `{"repo": ..., "target_path": ..., "output_dir": ...}`) → `runnable is False` with a non-empty `reason`.
- (e) the input `session_ctx` dict is NOT mutated by the call (env is built on a copy; deep-equality before/after holds, and the returned `env` is a distinct object containing `NGV2_SESSION_ID`).

Turns `tests/ngv2/test_stage_command_map_wired.py` GREEN. Pure/stdlib-only, deterministic (differential-fuzzable), no subprocess/I/O.
