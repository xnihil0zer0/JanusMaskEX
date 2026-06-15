---
dependencies:
  - "ngv2-analysis-handler"
interfaces: "from typing import Callable, Iterable, Optional, Sequence\nfrom ngv2.contracts import Finding, PoC\n\ndef build_hunt_handler(repo_path: str, *, analyzer_fn: Optional[Callable[..., list[Finding]]] = None, semgrep_finder: Optional[Callable[[str], list[dict]]] = None, pattern_finder: Optional[Callable[[str], list[dict]]] = None, now_fn: Optional[Callable[[], str]] = None) -> Callable[[], list[Finding]]: ...\ndef build_triage_handler(*, fp_patterns: Sequence = (), existing_titles: Iterable = ()) -> Callable[[list[Finding]], list[Finding]]: ...\ndef build_poc_handler(poc_builder: Callable[[Finding], PoC]) -> Callable[[list[Finding]], list[PoC]]: ...\ndef build_report_handler() -> Callable[[object, list], dict]: ...\ndef build_handlers(repo_path: str, *, runner: Callable, poc_builder: Callable[[Finding], PoC], target_spec: object = None, fp_patterns: Sequence = (), existing_titles: Iterable = (), semgrep_finder: Optional[Callable[[str], list[dict]]] = None, pattern_finder: Optional[Callable[[str], list[dict]]] = None, now_fn: Optional[Callable[[], str]] = None) -> dict: ...\n\n# Consumed default for analyzer_fn (sibling ngv2-analysis-handler):\ndef analyze(repo_path: str, *, semgrep_finder: Optional[Callable[[str], list[dict]]] = None, pattern_finder: Optional[Callable[[str], list[dict]]] = None, now_fn: Optional[Callable[[], str]] = None) -> list[Finding]: ..."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/handlers.py — pipeline handler-composition layer that assembles the toolkit into the handlers dict run_pipeline consumes

# Scope

Build the NEW single-file whole-file module `ngv2/handlers.py` at working_dir `/home/xnihil0zer0/NobleGreedv2`. It is the composition layer that closes the connectivity gap: a PURE, stdlib-only, deterministic module that wires the committed toolkit (`ngv2.analyzer.analyze`, `ngv2.fp_filter`, `ngv2.dedup`, `ngv2.report`, `ngv2.contracts`) into the callables `ngv2.pipeline.run_pipeline` consumes. Everything non-deterministic is injected (runner, poc_builder, finders, now_fn).

Frozen interface (authoritative for the oracle):
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
- `build_hunt_handler`: returns a zero-arg callable that calls `analyzer_fn` (defaulting to `ngv2.analyzer.analyze`) with `repo_path` and the injected finder/now seams, returning `list[Finding]`.
- `build_triage_handler`: returns a callable taking `list[Finding]`; it (a) converts findings to dicts via `Finding.to_dict()`, (b) filters them through `ngv2.fp_filter.filter_findings(dicts, fp_patterns)`, (c) rebuilds survivors via `Finding.from_dict`, (d) drops duplicate titles via `ngv2.dedup.filter_new(survivors, existing_titles)`, and returns the kept `list[Finding]`, preserving input order.
- `build_poc_handler`: returns a callable mapping `poc_builder` over each input `Finding`, returning `list[PoC]` in input order.
- `build_report_handler`: returns a callable `(state, reports) -> dict` that delegates to `ngv2.report.build_report(state, reports)`.
- `build_handlers`: returns a dict with EXACTLY the keys `run_pipeline` reads — `{'hunt': build_hunt_handler(...), 'triage': build_triage_handler(...), 'poc': build_poc_handler(poc_builder), 'runner': runner, 'report': build_report_handler(), 'target_spec': target_spec}` — such that `ngv2.pipeline.run_pipeline(build_handlers(...))` runs end-to-end with injected mock finders/runner/poc_builder and returns a dict whose `'report'` is the composed report.
- Deterministic; pure except for the injected `runner`, `poc_builder`, finders, and `now_fn`.

# Required plan shape
The leaf planner MUST emit EXACTLY two tasks. The oracle file MUST be named
`tests/test_handlers_wired.py` (the `_wired` suffix is REQUIRED — it makes this committed
oracle double as the wiring oracle the planner validator demands for a new-module leaf, and
it is genuinely a wiring oracle: it proves `ngv2/handlers.py` composes into
`ngv2.pipeline.run_pipeline`):
- TASK A (oracle): `meta_task_type: "test_authoring"`, top-level field `mutation_target: "ngv2.handlers"`, authoring `tests/test_handlers_wired.py` as the RED oracle for the frozen interface and the full behavior contract above — including the end-to-end check that `ngv2.pipeline.run_pipeline(build_handlers(...))` runs with injected mock finders/runner/poc_builder and returns a dict whose `'report'` is the composed report, and that `build_handlers` returns EXACTLY the keys `{'hunt','triage','poc','runner','report','target_spec'}`.
- TASK B (impl): creates the NEW whole-file module `ngv2/handlers.py` (NOT a symbol patch), declares TASK A's id in its `dependencies`, and sets `verification_command: "python -m pytest tests/test_handlers_wired.py -q"`.

# Non-Goals

No live exploit execution, no real LLM/model/network/subprocess calls, no GPU/ML training, no live huntr.com HTTP, no live MCP. No clock or randomness except via the injected `runner`/`poc_builder`/finders/`now_fn` seams. No edits to any existing committed module (`pipeline`, `pre_analysis`, `grounding`, `fp_filter`, `dedup`, `report`, `contracts`, `analyzer`, etc.) — `ngv2/handlers.py` only IMPORTS them. No third-party imports (stdlib only). Does NOT re-implement detection logic — the `hunt` handler delegates to `ngv2.analyzer.analyze` (the sibling `ngv2-analysis-handler`). Does NOT build the agentic spine/harness entrypoint (out of epic scope). Does NOT emit more than the two required tasks.

# Inputs

The external NobleGreedv2 repo at working_dir `/home/xnihil0zer0/NobleGreedv2`, holding the committed spine and toolkit this module composes/imports:
- `ngv2.pipeline.run_pipeline(handlers, *, success_marker)` — the orchestrator that reads `handlers['hunt']`, `handlers['triage']`, `handlers['poc']`, `handlers['runner']`, `handlers['report']`, and `handlers.get('target_spec')`.
- `ngv2.contracts.{Finding, PoC, LiveTestReport, SEVERITIES}` — `Finding` has `.to_dict()`, `.from_dict(...)`, `.validate()`.
- `ngv2.fp_filter.filter_findings(findings, patterns) -> list[dict]`.
- `ngv2.dedup.filter_new(findings, existing_titles) -> list[Finding]`.
- `ngv2.report.build_report(state, reports) -> dict`.

It consumes the sibling `ngv2-analysis-handler`'s frozen interface verbatim (default for `analyzer_fn`):
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

# Deliverables

ONE new single-file whole-file module `ngv2/handlers.py` plus its committed RED oracle `tests/test_handlers_wired.py` (carrying `mutation_target: "ngv2.handlers"`), verified GREEN with `python -m pytest tests/test_handlers_wired.py -q`.

It exposes the frozen interface verbatim:
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
`build_handlers` returns the dict with EXACTLY the keys `{'hunt','triage','poc','runner','report','target_spec'}` so that `ngv2.pipeline.run_pipeline(build_handlers(...))` runs end-to-end and returns a dict whose `'report'` is the composed report. `build_hunt_handler` defaults `analyzer_fn` to `ngv2.analyzer.analyze`.
