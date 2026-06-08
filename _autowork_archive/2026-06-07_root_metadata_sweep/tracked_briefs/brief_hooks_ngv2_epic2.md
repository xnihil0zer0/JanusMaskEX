---
epic: true
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

NobleGreedv2 Epic-2: hunt->triage->poc->detonate->report orchestration over the Epic-1 substrate.

# Scope

Decompose this epic into EXACTLY FOUR independent child briefs that build the
DETERMINISTIC orchestration layer of NobleGreedv2's hunting runtime into the
external repo (its own git + venv). All four are pure, deterministic,
stdlib-only Python modules under the `ngv2/` package, each pinned by a
HAND-AUTHORED ORACLE THAT IS ALREADY COMMITTED to the NobleGreedv2 repo — so
every child is IMPL-ONLY (it must NOT author tests). Each child is a NEW single
module file submitted WHOLE-FILE.

The dangerous LIVE work (running real exploit PoCs against real targets) is NOT
built here — it stays data-driven at NGv2 runtime. This epic manufactures only
the deterministic, mock-testable tooling that ORCHESTRATES that work.

All four children build ON TOP of the ALREADY-COMMITTED Epic-1 substrate and
import from it; NONE of the four depends on another Epic-2 child (they are
mutually independent and may build in any order). The substrate they consume:
- `ngv2.contracts`: `Finding(id, target, category, severity, title, description,
  evidence=[])`, `PoC(finding_id, language, code, entrypoint)`,
  `LiveTestReport(poc_finding_id, verdict, exit_code, stdout, stderr, duration_ms)`,
  the tuples `SEVERITIES = ('low','medium','high','critical')` and
  `VERDICTS = ('confirmed','refuted','error','inconclusive')`; every dataclass has
  `to_dict()`, classmethod `from_dict(d)`, and `validate()`.
- `ngv2.state_machine`: `HuntState(phase='hunt', findings=[])`, `HuntStateMachine`
  with `add_finding`, `can_transition`, `transition`, `to_dict`, `from_dict`, and
  `PHASES = ('hunt','triage','poc','detonate','report','done')`.
- `ngv2.detonation`: `DetonationChamber(success_marker='VULNERABLE')` with
  `detonate(poc, target_spec, runner) -> LiveTestReport`, where `runner` is an
  injected callable `runner(poc, target_spec) -> (exit_code, stdout, stderr, duration_ms)`.

Produce these four children with these exact slugs and contracts:

## Child 1 — slug `ngv2-grounding-adapter` (depends only on the committed substrate)
Builds NEW file `ngv2/grounding.py`. A deterministic adapter that turns a
semgrep-shaped static-analysis JSON report into `ngv2.contracts.Finding` objects.
NO static-analysis tool is invoked; the tool output is passed in as a dict (pure
parse/normalize). MUST `from ngv2.contracts import Finding, SEVERITIES`.
- `normalize_severity(raw: str) -> str`: case-insensitive map of a tool severity
  string to a member of `SEVERITIES`. Mapping: `CRITICAL -> 'critical'`,
  `ERROR -> 'high'`, `WARNING -> 'medium'`, `INFO -> 'low'`; any unknown value
  returns the safe default `'low'`. The returned value is ALWAYS in `SEVERITIES`.
- `parse_semgrep(report: dict, target: str) -> list[Finding]`: read
  `report.get('results', [])`; for each result at 0-based index `i` build a
  `Finding` with: `id = f"{result['check_id']}-{i}"` (deterministic + unique per
  result); `target = target`; `category =` the first CWE in
  `result['extra']['metadata']['cwe']` if that list is present and non-empty, else
  `result['check_id']` (always a non-empty str); `severity =
  normalize_severity(result['extra']['severity'])`; `title = result['extra']['message']`;
  `description = result['extra']['message']`; `evidence =
  [f"{result['path']}:{result['start']['line']}-{result['end']['line']}"]`. Every
  returned Finding must satisfy `Finding.validate()`. An empty or missing
  `results` list returns `[]`. Use `.get(...)` defensively so a missing
  `metadata`/`cwe` falls back to the check_id without raising.
- Verification: `python -m pytest tests/test_grounding.py -q` (oracle committed).

## Child 2 — slug `ngv2-poc-runner` (depends only on the committed substrate)
Builds NEW file `ngv2/poc_runner.py`. The deterministic runner-adapter contract
the `DetonationChamber` consumes, plus deterministic mock/scripted runners for
tests. The REAL subprocess/bwrap runner lives at NGv2 runtime and is NOT built
here (JM never runs a real exploit). MUST `from ngv2.contracts import PoC` (used
for the runner's documented input type).
- Module constant `RUNNER_RESULT_FIELDS = ('exit_code', 'stdout', 'stderr',
  'duration_ms')` documenting the 4-tuple a runner returns (the exact order the
  DetonationChamber unpacks).
- `make_mock_runner(exit_code: int = 0, stdout: str = '', stderr: str = '',
  duration_ms: int = 0)`: returns a callable `runner(poc, target_spec)` that
  ignores its arguments and returns the fixed tuple
  `(exit_code, stdout, stderr, duration_ms)`.
- `make_scripted_runner(script: dict)`: `script` maps a `poc.finding_id` (str) to
  a 4-tuple `(exit_code, stdout, stderr, duration_ms)`. Returns a callable
  `runner(poc, target_spec)` that looks up `poc.finding_id` in `script` and
  returns its tuple; for an UNMAPPED finding_id it returns a deterministic default
  `(None, '', '', 0)` (inconclusive-shaped: empty stdout, non-negative int
  duration). Never raises on an unmapped id.
- Verification: `python -m pytest tests/test_poc_runner.py -q` (oracle committed).

## Child 3 — slug `ngv2-report` (depends only on the committed substrate)
Builds NEW file `ngv2/report.py`. A deterministic report builder + markdown
renderer over a `HuntState` (its `findings`) and the detonation `LiveTestReport`s.
Pure (no I/O). It receives objects and calls their `.to_dict()`; it does not
re-implement the dataclasses.
- `build_report(state, reports) -> dict`: `state` is a `HuntState`-like object
  exposing `.phase` (str) and `.findings` (list of `Finding`); `reports` is a list
  of `LiveTestReport`. Returns a dict with EXACT keys:
  `{'phase': state.phase, 'findings': [f.to_dict() for f in state.findings],
  'results': [r.to_dict() for r in reports], 'summary': {...}}`. The `summary`
  sub-dict has: `'total_findings': len(state.findings)`, and one count per verdict
  in `VERDICTS` — i.e. `'confirmed'`, `'refuted'`, `'error'`, `'inconclusive'` —
  each being the number of `reports` whose `.verdict` equals that value.
- `render_markdown(report: dict) -> str`: returns a huntr-submission-shaped
  markdown string that STARTS with `'#'` (a top-level header) and CONTAINS, for
  each finding, its `title` and `target`, and CONTAINS each result's verdict text
  (so e.g. a confirmed finding's section contains the word `confirmed`). Build it
  by reading the dict produced by `build_report` (do not require live objects).
- Verification: `python -m pytest tests/test_report.py -q` (oracle committed).

## Child 4 — slug `ngv2-pipeline-orchestrator` (depends only on the committed substrate)
Builds NEW file `ngv2/pipeline.py`. Drives a `HuntStateMachine` through
hunt -> triage -> poc -> detonate -> report -> done over INJECTED phase handlers
(callables). Pure + deterministic + mock-testable: detonation runs through the
injected runner via a `DetonationChamber` (no real subprocess/network). MUST
`from ngv2.state_machine import HuntStateMachine` and
`from ngv2.detonation import DetonationChamber` (the dependency edges).
- `run_pipeline(handlers: dict, *, success_marker: str = 'VULNERABLE') -> dict`:
  1. Create `sm = HuntStateMachine()`.
  2. For each finding returned by `handlers['hunt']()` call `sm.add_finding(f)`.
  3. `sm.transition('triage')`; set `kept = handlers['triage'](list(sm.state.findings))`
     then `sm.state.findings = list(kept)` (triage may DROP findings).
  4. `sm.transition('poc')`; `pocs = handlers['poc'](list(sm.state.findings))`.
  5. `sm.transition('detonate')`; create `chamber =
     DetonationChamber(success_marker=success_marker)`; for each poc in `pocs`
     compute `chamber.detonate(poc, handlers.get('target_spec'), handlers['runner'])`
     and collect the `LiveTestReport`s in order.
  6. `sm.transition('report')`; if `'report' in handlers`, call
     `report = handlers['report'](sm.state, reports)` else `report = None`.
  7. `sm.transition('done')`.
  8. Return `{'phase': sm.state.phase, 'reports': [r.to_dict() for r in reports],
     'report': report}` (so `phase` is `'done'`; `reports` is a list of
     `LiveTestReport` dicts in poc order; `report` is the report handler's output
     or None). An empty findings list still walks every transition to `'done'`
     with `reports == []`.
- Verification: `python -m pytest tests/test_pipeline.py -q` (oracle committed).

# Non-Goals

- Do NOT author, create, or modify ANY test file. The four oracles
  (`tests/test_grounding.py`, `tests/test_poc_runner.py`, `tests/test_report.py`,
  `tests/test_pipeline.py`) are ALREADY COMMITTED in the NobleGreedv2 repo; every
  child is IMPL-ONLY and must emit NO `test_authoring` task. Each child's
  verification_command runs ONLY its own already-committed oracle.
- Do NOT use eval, exec, or `__import__`. Do NOT run a real subprocess, open a
  socket, touch the network, or execute exploit code — runners are injected and
  the only "execution" is calling an injected callable.
- Do NOT add I/O, file access, globals, or randomness; stdlib only.
- Do NOT redefine the substrate dataclasses or the state machine — import them
  from `ngv2.contracts` / `ngv2.state_machine` / `ngv2.detonation`.
- Do NOT add fields, public functions, or symbols beyond those specified; do NOT
  change function names, signatures, dict keys, or return shapes.
- Do NOT collapse the four modules into one, do NOT add a fifth child, and do NOT
  introduce any dependency between the four children (each reads ONLY the
  already-committed substrate).

# Inputs

- The external NobleGreedv2 repo at the epic `working_dir`
  (`/home/xnihil0zer0/NobleGreedv2`), which already contains the committed Epic-1
  substrate (`ngv2/contracts.py`, `ngv2/state_machine.py`, `ngv2/detonation.py`)
  and the four committed Epic-2 oracles (`tests/test_grounding.py`,
  `tests/test_poc_runner.py`, `tests/test_report.py`, `tests/test_pipeline.py`).
- Each child consumes the substrate via plain imports; the substrate's public
  shapes are listed in Scope above and are stable (already committed + tested).

# Deliverables

- Child `ngv2-grounding-adapter` produces NEW `ngv2/grounding.py` exposing
  `normalize_severity(raw) -> str` and `parse_semgrep(report, target) -> list[Finding]`
  as specified, importing `Finding, SEVERITIES` from `ngv2.contracts`. Verified by
  the committed `tests/test_grounding.py`.
- Child `ngv2-poc-runner` produces NEW `ngv2/poc_runner.py` exposing
  `RUNNER_RESULT_FIELDS`, `make_mock_runner(...)`, and `make_scripted_runner(script)`
  returning runner callables matching the DetonationChamber's
  `(exit_code, stdout, stderr, duration_ms)` contract, importing `PoC` from
  `ngv2.contracts`. Verified by the committed `tests/test_poc_runner.py`.
- Child `ngv2-report` produces NEW `ngv2/report.py` exposing
  `build_report(state, reports) -> dict` (with keys `phase`, `findings`, `results`,
  `summary` where summary has `total_findings` + a count per `VERDICTS` member) and
  `render_markdown(report) -> str`. Verified by the committed `tests/test_report.py`.
- Child `ngv2-pipeline-orchestrator` produces NEW `ngv2/pipeline.py` exposing
  `run_pipeline(handlers, *, success_marker='VULNERABLE') -> dict` driving the
  HuntStateMachine hunt->...->done over injected handlers and a DetonationChamber,
  importing `HuntStateMachine` from `ngv2.state_machine` and `DetonationChamber`
  from `ngv2.detonation`. Verified by the committed `tests/test_pipeline.py`.
