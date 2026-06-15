---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
epic: true
child_epics: false
---

# Title

NobleGreedv2 Wire-Up Epic — build the handler-composition layer that connects the
existing deterministic toolkit to the `pipeline.run_pipeline` orchestrator. This closes
the single real connectivity gap found by the wire-up sweep: the toolkit (~40 committed
modules) and the orchestrator are two disconnected halves because nothing assembles the
toolkit into the `handlers` dict that `run_pipeline` consumes.

# Scope

NobleGreedv2 is a clean-room rebuild of an autonomous security bug-hunter, manufactured by
JanusMask's gated pipeline. The hunt->triage->poc->detonate->report SPINE exists:
`ngv2.pipeline.run_pipeline(handlers: dict, *, success_marker='VULNERABLE')` walks
`ngv2.state_machine.HuntStateMachine` and calls INJECTED handler callables:

```
findings = handlers['hunt']()                         # -> list[ngv2.contracts.Finding]
kept     = handlers['triage'](list(state.findings))   # -> list[Finding]
pocs     = handlers['poc'](list(state.findings))      # -> list[ngv2.contracts.PoC]
report   = DetonationChamber().detonate(poc, handlers.get('target_spec'), handlers['runner'])  # per poc
report   = handlers['report'](state, reports)         # -> dict
```

Today NOTHING builds that `handlers` dict from the toolkit — those callables exist only
inside test fixtures. The analysis/triage/poc/report modules are built (`pre_analysis`,
`grounding`, `fp_filter`, `dedup`, `report`, `poc_runner`, etc.) but are never composed
into the pipeline. This epic builds the composition layer that wires them in. Both new
modules are PURE / injected-seam: no live exploit execution, no real LLM/model/network/
subprocess, no clock or randomness except through injected parameters.

This is preparation for the agentic spine/harness (not yet built). When the spine lands, its
single entrypoint will call `build_handlers(...)` then `run_pipeline(handlers)`, making the
whole toolkit reachable from one root. This epic supplies the seam the spine plugs into.

# Your decomposition task

Decompose this epic into EXACTLY TWO leaf child briefs (NOT epics): one per new module
below. Carry `working_dir: "/home/xnihil0zer0/NobleGreedv2"` on every child brief.
`ngv2-pipeline-handlers` MUST list `ngv2-analysis-handler` in its `dependencies` (handlers
imports analyzer). Restate each module's frozen interface verbatim in the producer's
`deliverables` and the consumer's `inputs` so the contract survives independent re-planning.

Each leaf is built TEST-FIRST with an AUTOMATICALLY-AUTHORED oracle. Each child brief MUST
drive the leaf planner to emit a two-task plan:
1. a `test_authoring` task that authors `tests/test_<module>.py` with top-level field
   `mutation_target: "ngv2.<module>"`, building the RED oracle from the frozen interface; then
2. an implementation task that creates the NEW single-file whole-file module
   `ngv2/<module>.py`, depends on the oracle task, and is verified with
   `python -m pytest tests/test_<module>.py -q`.

Each child brief must contain a `# Required plan shape` section spelling out exactly those
two tasks (the oracle task carrying `mutation_target`, the impl task depending on it and
carrying the pytest verification_command).

# The body of work — 2 capabilities to build

## 1. `ngv2/analyzer.py` — detection orchestrator (the legacy code_audit/analyzer.py role)

Pure, stdlib-only, deterministic; all I/O behind injected seams. Composes the existing
`ngv2.pre_analysis.run_pre_analysis` output into `ngv2.contracts.Finding` objects.

Frozen interface:
```python
from typing import Callable, Optional
from ngv2.contracts import Finding

def analyze(
    repo_path: str,
    *,
    semgrep_finder: Optional[Callable[[str], list[dict]]] = None,
    pattern_finder: Optional[Callable[[str], list[dict]]] = None,
    now_fn: Optional[Callable[[], str]] = None,
) -> list[Finding]: ...
```
Behavior contract (authoritative for the oracle):
- Calls `ngv2.pre_analysis.run_pre_analysis(repo_path, semgrep_finder=semgrep_finder,
  pattern_finder=pattern_finder, now_fn=now_fn)` to get the merged report.
- Converts the report's `cross_validated`, `semgrep_only`, and `scanner_only` finding dicts
  into `Finding` objects (in that source-bucket order). For a finding dict `d` at index `i`
  within its bucket `src` (one of `'xval'|'semgrep'|'scanner'`):
  - `id = f"{src}-{i}"`
  - `target = repo_path`
  - `category = str(d.get('rule_id') or d.get('id') or d.get('category') or 'unknown')`
  - `severity = _normalize_severity(d.get('severity'))` where the normalizer maps via
    `ngv2.grounding.normalize_severity` and any value not in `ngv2.contracts.SEVERITIES`
    falls back to `'low'`.
  - `title = str(d.get('message') or d.get('title') or category)`
  - `description = title`
  - `evidence = [f"{d.get('file','')}:{d.get('line','')}"]`
- Every returned `Finding` passes `.validate()`.
- Deterministic for identical finder outputs; the returned list is stable-ordered by bucket
  then by the original within-bucket order produced by `run_pre_analysis`.
- No real semgrep/network/clock: when finders/now_fn are omitted, the `pre_analysis`
  defaults apply (already pure). Tests inject mock finders returning known dicts.

## 2. `ngv2/handlers.py` — pipeline handler-composition layer

Pure, stdlib-only, deterministic; composes committed toolkit modules into the callables
`run_pipeline` consumes. Imports `ngv2.analyzer.analyze`, `ngv2.fp_filter`, `ngv2.dedup`,
`ngv2.report`, `ngv2.contracts`.

Frozen interface:
```python
from typing import Callable, Iterable, Optional, Sequence
from ngv2.contracts import Finding, PoC

def build_hunt_handler(
    repo_path: str,
    *,
    analyzer_fn: Optional[Callable[..., list[Finding]]] = None,
    semgrep_finder: Optional[Callable[[str], list[dict]]] = None,
    pattern_finder: Optional[Callable[[str], list[dict]]] = None,
    now_fn: Optional[Callable[[], str]] = None,
) -> Callable[[], list[Finding]]: ...

def build_triage_handler(
    *,
    fp_patterns: Sequence = (),
    existing_titles: Iterable = (),
) -> Callable[[list[Finding]], list[Finding]]: ...

def build_poc_handler(
    poc_builder: Callable[[Finding], PoC],
) -> Callable[[list[Finding]], list[PoC]]: ...

def build_report_handler() -> Callable[[object, list], dict]: ...

def build_handlers(
    repo_path: str,
    *,
    runner: Callable,
    poc_builder: Callable[[Finding], PoC],
    target_spec: object = None,
    fp_patterns: Sequence = (),
    existing_titles: Iterable = (),
    semgrep_finder: Optional[Callable[[str], list[dict]]] = None,
    pattern_finder: Optional[Callable[[str], list[dict]]] = None,
    now_fn: Optional[Callable[[], str]] = None,
) -> dict: ...
```
Behavior contract (authoritative for the oracle):
- `build_hunt_handler`: returns a zero-arg callable that calls `analyzer_fn` (defaulting to
  `ngv2.analyzer.analyze`) with `repo_path` and the injected finder/now seams, returning
  `list[Finding]`.
- `build_triage_handler`: returns a callable taking `list[Finding]`; it (a) converts findings
  to dicts via `Finding.to_dict()`, (b) filters them through
  `ngv2.fp_filter.filter_findings(dicts, fp_patterns)`, (c) rebuilds survivors via
  `Finding.from_dict`, (d) drops duplicate titles via
  `ngv2.dedup.filter_new(survivors, existing_titles)`, and returns the kept `list[Finding]`,
  preserving input order.
- `build_poc_handler`: returns a callable mapping `poc_builder` over each input `Finding`,
  returning `list[PoC]` in input order.
- `build_report_handler`: returns a callable `(state, reports) -> dict` that delegates to
  `ngv2.report.build_report(state, reports)`.
- `build_handlers`: returns a dict with EXACTLY the keys `run_pipeline` reads —
  `{'hunt': build_hunt_handler(...), 'triage': build_triage_handler(...),
  'poc': build_poc_handler(poc_builder), 'runner': runner,
  'report': build_report_handler(), 'target_spec': target_spec}` — such that
  `ngv2.pipeline.run_pipeline(build_handlers(...))` runs end-to-end with injected mock
  finders/runner/poc_builder and returns a dict whose `'report'` is the composed report.
- Deterministic; pure except for the injected `runner`, `poc_builder`, finders, and `now_fn`.

# Required plan shape (applies to BOTH leaves)

Each leaf's plan MUST be exactly two tasks:
- TASK A (oracle): `meta_task_type: "test_authoring"`, top-level `mutation_target:
  "ngv2.<module>"`, authoring `tests/test_<module>.py` as the RED oracle for the frozen
  interface above.
- TASK B (impl): creates the NEW whole-file module `ngv2/<module>.py`, declares TASK A's id
  in its `dependencies`, and sets `verification_command: "python -m pytest
  tests/test_<module>.py -q"`. New whole-file module — NOT a symbol patch.

# Non-Goals

No live exploit execution, real LLM/model/network/subprocess calls, GPU/ML training, live
huntr.com HTTP, or live MCP. No edits to existing committed modules (`pipeline`,
`pre_analysis`, `grounding`, `fp_filter`, `dedup`, `report`, `contracts`, etc.) — the two
new modules only IMPORT them. No third-party imports (stdlib only; injected seams for any
non-determinism). `ngv2/analyzer.py` must not import `ngv2/handlers.py`.

# Inputs

The external NobleGreedv2 repo at `working_dir /home/xnihil0zer0/NobleGreedv2`, holding the
committed spine and toolkit: `ngv2.pipeline.run_pipeline(handlers, *, success_marker)`,
`ngv2.contracts.{Finding,PoC,LiveTestReport,SEVERITIES}`,
`ngv2.pre_analysis.run_pre_analysis(repo_path, *, semgrep_finder, pattern_finder, now_fn) -> dict`
(keys `cross_validated`, `semgrep_only`, `scanner_only`, ...),
`ngv2.grounding.normalize_severity(raw) -> str`,
`ngv2.fp_filter.filter_findings(findings, patterns) -> list[dict]`,
`ngv2.dedup.filter_new(findings, existing_titles) -> list[Finding]`,
`ngv2.report.build_report(state, reports) -> dict`. The legacy corpus at
`/mnt/ai-data/NobleGreed-legacy` (`services/code_audit/analyzer.py`, `grounding.py`) is the
design source for the analyzer's role; only the frozen interface + committed oracle is
authoritative for the build.

# Deliverables

Two NEW single-file whole-file `ngv2/*.py` modules — `ngv2/analyzer.py` and
`ngv2/handlers.py` — each built test-first with an automatically-authored committed oracle
at `tests/test_<module>.py` and verified with `python -m pytest tests/test_<module>.py -q`.
Together they compose the existing toolkit into the `handlers` dict that
`ngv2.pipeline.run_pipeline` consumes, connecting the toolkit to the orchestrator.
