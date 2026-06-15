---
epic: false
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "pure telemetry-to-prompt formatter; detonation acceptance gate over an injected runner"
---

# Title

Feedback-guided PoC synthesis loop for NobleGreedv2 (Agentic Spine Epic D — RE-SCOPED)

Build the pipeline-buildable half of the detonation system: a pure telemetry-to-diagnostic formatter
and an extended acceptance gate that consumes an **injected** runner result. The live bwrap detonation
runner is explicitly QUARANTINED out of this epic — it is irreducibly side-effecting and
non-deterministic, so the dual-agent fuzz gate and a deterministic oracle cannot verify it, and the
JanusMaskJR fuzz sandbox blocks the very `execve`/`fork`/`socket` syscalls it needs. NobleGreedv2
already solved this with an injected-runner seam (`detonation.py` + `poc_runner.py` treat the exploit
as data); this epic keeps that seam and only builds the pure pieces around it. The real runner is
delivered separately as an owner hand-authored, irreducible-tier artifact (see
SPINE_IMPLEMENTATION_PLAN.md §4 and the handoff). It is a single multi-task **leaf** brief (two
tasks), NOT a decomposed epic.

# Scope

- `ngv2/feedback_synth.py` (NEW, whole-file): `build_diagnostic_prompt(prev_poc, telemetry)` — pure
  string transform. Truncate stdout/stderr (first 250 / last 750 lines, prioritizing tracebacks),
  regex-strip deprecation noise, classify the failure into the three detonation classes
  `ENV_PATH_ERROR` / `SYNTAX_API_ERROR` / `PAYLOAD_REFUTED`, and emit the structured diagnostic
  markdown. No I/O. **Classification note:** these three classes are *defined by this module*; derive
  them by matching telemetry against the existing building blocks — `ngv2/crash_analyzer.py::
  ERROR_PATTERNS` is `Dict[str, List[str]]` keyed `rate_limit, oom_memory, mcp_error, git_error,
  auth_error, network_error, import_error, scope_creep` (e.g. `import_error`/`network_error` →
  `ENV_PATH_ERROR`), and `ngv2/trace_parser.py::infer_failure_mode(entry) -> Optional[str]` returns a
  short failure-mode label. Reuse those as inputs; do not assume `ERROR_PATTERNS` already contains the
  three class names (it does not).
- `ngv2/detonation.py` (EDIT, ADDITIVE): extend the acceptance gate with a **Semantic-Oracle** verdict
  helper that, given an injected runner result `(exit_code, stdout, stderr, fs_snapshot_diff)`,
  returns `confirmed` only when `exit_code==0` AND the `success_marker` is present AND the expected
  file-mutation signature is observed — upgrading the weak exit-code+grep gate. Preserve the existing
  `DetonationChamber` — which is the **only** top-level symbol in `detonation.py`. The runner factories
  `make_mock_runner`/`make_scripted_runner` live in `ngv2/poc_runner.py` (NOT in `detonation.py`);
  consume them unchanged as the injected-runner seam — do not move, redefine, or re-emit them here.

# Non-Goals

The word integration appears here deliberately. OUT OF BOUNDS — DO NOT DISPATCH AS A LEAF: any real
`bwrap`/`subprocess`/`shutil.copytree`/`pip`/network code; any module that spawns a process or opens a
socket; the `HardenedSandboxRunner` from the blueprint (it omits `--die-with-parent`, `--new-session`,
`--cap-drop`, seccomp, and hardcodes a libfaketime path that does not exist on the host). Those live in
the hand-authored runner outside this epic. Also out of bounds: faketime for determinism (reuse JM's
`autocompiler/determinism.py` sitecustomize approach); whole-repo copytree per attempt.

# Inputs

Already built — consume as-is and DO NOT modify their contracts: `ngv2/detonation.py::DetonationChamber`
(the only symbol there; extend the gate via an additive helper only), `ngv2/poc_runner.py`
(`RUNNER_RESULT_FIELDS = ('exit_code','stdout','stderr','duration_ms')`, `make_mock_runner`,
`make_scripted_runner` — the injected runner seam), `ngv2/crash_analyzer.py::ERROR_PATTERNS`,
`ngv2/trace_parser.py::infer_failure_mode`, `ngv2/variant_generator.py`. For the hand-authored runner
(NOT part of this epic), the reference is JanusMaskJR `harness/agent_jail.py::build_jail_argv(cmd, *,
repo_root, work_dir, state_dir, home=None, extra_ro=(), extra_rw=(), dbus_proxy_socket=None,
bind_credentials=True, js_node_bin_dir=None)` (call with `bind_credentials=False, extra_ro=[wheels],
extra_rw=[workspace]`), `harness/sandbox.py::_install_seccomp`, and the cleanroom strace +
`RV-MUTATION` FS-snapshot recipes from
`agentic_spine_research/os-repos/trustworthy-env/detection/audit_mvp.py:1550-1686`.

# Deliverables

1. `ngv2/feedback_synth.py` — oracle feeds fixed telemetry tuples and asserts the exact diagnostic
   markdown, the truncation bounds (first 250 / last 750 lines), and the correct failure classification
   into `ENV_PATH_ERROR`/`SYNTAX_API_ERROR`/`PAYLOAD_REFUTED` for each class. Pure → fully fuzzable.
   meta_task_type `planner_tooling`.
2. `ngv2/detonation.py` (additive gate) — oracle drives the extended gate with a mock runner result
   (from `poc_runner.make_mock_runner`/`make_scripted_runner`) and asserts `confirmed` only on
   (exit 0 + marker + expected FS mutation), and `refuted`/`error` otherwise; asserts `DetonationChamber`
   is unchanged and that `make_mock_runner`/`make_scripted_runner` remain importable from
   `poc_runner.py`. Pure over the injected result → fuzzable. meta_task_type `validation`.

# Required plan shape

Two leaf tasks, module-creating first. This is a single non-epic plan — the planner emits these tasks
directly; do NOT decompose into child briefs.

- LEAF D1 `feedback_synth` — meta_task_type `planner_tooling`, NEW whole-file, pure/fuzzable.
- LEAF D2 `detonation_semantic_gate` — meta_task_type `validation`, EDIT `ngv2/detonation.py`
  additively; preserves `DetonationChamber`.

PINNED CONTRACTS (the committed oracles assert these EXACTLY — build to them; NO time/random anywhere):
- D1 `build_diagnostic_prompt(prev_poc, telemetry)->str` pure/deterministic. telemetry dict keys consulted:
  exit_code(int|None), stdout(str), stderr(str), marker_present(bool), all optional. Classify (output MUST
  contain the class token verbatim), precedence ENV>SYNTAX>REFUTED: `ENV_PATH_ERROR` (import_error/
  network_error signatures e.g. ModuleNotFoundError/'connection refused'); `SYNTAX_API_ERROR` (SyntaxError
  or API-misuse TypeError/AttributeError traceback); `PAYLOAD_REFUTED` (clean run exit_code==0, no env/syntax
  signature, marker_present false). Truncation: keep at most first 250 + last 750 lines of EACH stream;
  reference prev_poc via its finding_id; deterministic (call twice equal).
- D2 NEW top-level helper `semantic_verdict(exit_code, stdout, stderr, fs_snapshot_diff, *, success_marker,
  expected_fs_signature)->str`: `'confirmed'` ONLY when exit_code==0 AND success_marker in (stdout OR stderr)
  AND expected_fs_signature substring in fs_snapshot_diff; `'error'` when exit_code nonzero (dominates);
  `'refuted'` when exit_code in (0,None) but the confirmed bar isn't met. DetonationChamber and
  poc_runner.make_mock_runner/make_scripted_runner stay unchanged/importable.

D2 PATCH FORMAT (MANDATORY — additive, adds ONLY the new `semantic_verdict` function): emit a single
`__JANUSMASK_PATCHES__` with EXACTLY ONE entry kind `'symbol'`, name `'DetonationChamber'` (the only
existing top-level symbol — the R-ANCHOR). In `code`, reproduce `DetonationChamber` BYTE-FOR-BYTE exactly as
staged read-only at `{WORK_DIR}/inbox/targets/ngv2/detonation.py` (it is ~26 lines — copy it verbatim, change
NOTHING in it, including its `from ngv2.contracts import ...` is at module top and stays), then append your new
top-level `def semantic_verdict(...)` after it. The harness inserts the new function next to the anchor and
preserves every other byte. DO NOT modify DetonationChamber's logic; DO NOT emit whole-file. The oracle
asserts DetonationChamber is unchanged.

**Plan-shape invariants for EVERY leaf:** every leaf MUST list at least two edge_cases in its test_spec and mirror EACH into regression_tests or property_tests (the plan validator hard-drops any leaf without this); name a `*_wired` oracle in `verification_command` — required
because the plan validator resolves `files_touched` against the JanusMaskJR repo root, where these
NGv2 paths are absent, so every leaf reads as module-creating (the runtime wire-up gate no-ops for
external targets). Carry the literal word `integration` in each leaf's `non_goals`. NEW modules emit
whole-file, one file per task; the EDIT leaf preserves all existing symbols.

EXPLICITLY NOT A LEAF: the live runner `ngv2/poc_runner_live.py`. It is irreducible-tier, owner
hand-authored, reuses `build_jail_argv` + a detonation seccomp profile + wheels-only gathering, and is
reviewed by the owner before it is wired. The overseer must NEVER place it on the allowlist or stage it
as a task. Sequencing: do not allowlist this epic until Epic C is green.
