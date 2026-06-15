---
interfaces: "from typing import Callable, Optional\nfrom ngv2.contracts import Finding\n\ndef analyze(\n    repo_path: str,\n    *,\n    semgrep_finder: Optional[Callable[[str], list[dict]]] = None,\n    pattern_finder: Optional[Callable[[str], list[dict]]] = None,\n    now_fn: Optional[Callable[[], str]] = None,\n) -> list[Finding]: ..."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/analyzer.py — detection orchestrator that composes pre_analysis output into Finding objects

# Scope

Build the NEW single-file whole-file module `ngv2/analyzer.py` at working_dir `/home/xnihil0zer0/NobleGreedv2`. It is the detection orchestrator (the legacy `services/code_audit/analyzer.py` role): a PURE, stdlib-only, deterministic function that drives `ngv2.pre_analysis.run_pre_analysis` and converts its merged report into `ngv2.contracts.Finding` objects. All non-determinism (semgrep finder, pattern finder, clock) is behind injected seams.

Frozen interface (authoritative for the oracle):
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
- Calls `ngv2.pre_analysis.run_pre_analysis(repo_path, semgrep_finder=semgrep_finder, pattern_finder=pattern_finder, now_fn=now_fn)` to get the merged report.
- Converts the report's `cross_validated`, `semgrep_only`, and `scanner_only` finding dicts into `Finding` objects, in that source-bucket order. For a finding dict `d` at index `i` within its bucket `src` (one of `'xval'|'semgrep'|'scanner'`):
  - `id = f"{src}-{i}"`
  - `target = repo_path`
  - `category = str(d.get('rule_id') or d.get('id') or d.get('category') or 'unknown')`
  - `severity = _normalize_severity(d.get('severity'))` where the normalizer maps via `ngv2.grounding.normalize_severity` and any value not in `ngv2.contracts.SEVERITIES` falls back to `'low'`.
  - `title = str(d.get('message') or d.get('title') or category)`
  - `description = title`
  - `evidence = [f"{d.get('file','')}:{d.get('line','')}"]`
- Every returned `Finding` passes `.validate()`.
- Deterministic for identical finder outputs; the returned list is stable-ordered by bucket then by the original within-bucket order produced by `run_pre_analysis`.
- No real semgrep/network/clock: when finders/now_fn are omitted, the `pre_analysis` defaults apply (already pure). Tests inject mock finders returning known dicts.

# Required plan shape
The leaf planner MUST emit EXACTLY two tasks. The oracle file MUST be named
`tests/test_analyzer_wired.py` (the `_wired` suffix is REQUIRED — it makes this committed
oracle double as the wiring oracle the planner validator demands for a new-module leaf, and
it asserts that `analyze` produces `Finding` objects consumable by the hunt-handler/pipeline
composition path):
- TASK A (oracle): `meta_task_type: "test_authoring"`, top-level field `mutation_target: "ngv2.analyzer"`, authoring `tests/test_analyzer_wired.py` as the RED oracle for the frozen interface and the full behavior contract above (bucket order, id/target/category/severity/title/description/evidence mapping, severity fallback to `'low'`, `.validate()` on every Finding, determinism). Tests inject mock `semgrep_finder`/`pattern_finder`/`now_fn` returning known dicts.
- TASK B (impl): creates the NEW whole-file module `ngv2/analyzer.py` (NOT a symbol patch), declares TASK A's id in its `dependencies`, and sets `verification_command: "python -m pytest tests/test_analyzer_wired.py -q"`.

# Non-Goals

No live exploit execution, no real LLM/model/network/subprocess calls, no GPU/ML training, no live huntr.com HTTP, no live MCP. No clock or randomness except through the injected `now_fn` / finder seams. No edits to any existing committed module (`pipeline`, `pre_analysis`, `grounding`, `fp_filter`, `dedup`, `report`, `contracts`, etc.) — `ngv2/analyzer.py` only IMPORTS them. No third-party imports (stdlib only). `ngv2/analyzer.py` MUST NOT import `ngv2/handlers.py`. Does NOT build the `handlers` dict or any pipeline composition — that is the sibling `ngv2-pipeline-handlers`. Does NOT emit more than the two required tasks.

# Inputs

The external NobleGreedv2 repo at working_dir `/home/xnihil0zer0/NobleGreedv2`, holding the committed toolkit this module composes/imports:
- `ngv2.pre_analysis.run_pre_analysis(repo_path, *, semgrep_finder, pattern_finder, now_fn) -> dict` returning a merged report with keys `cross_validated`, `semgrep_only`, `scanner_only` (and others); each is a list of finding dicts.
- `ngv2.grounding.normalize_severity(raw) -> str`.
- `ngv2.contracts.Finding` (constructed with `id`, `target`, `category`, `severity`, `title`, `description`, `evidence`; has `.validate()`) and `ngv2.contracts.SEVERITIES` (the allowed severity set).
The legacy corpus at `/mnt/ai-data/NobleGreed-legacy` (`services/code_audit/analyzer.py`, `grounding.py`) is the design source for the analyzer's role only; the frozen interface + committed oracle is authoritative for the build.

# Deliverables

ONE new single-file whole-file module `ngv2/analyzer.py` plus its committed RED oracle `tests/test_analyzer_wired.py` (carrying `mutation_target: "ngv2.analyzer"`), verified GREEN with `python -m pytest tests/test_analyzer_wired.py -q`.

It exposes the frozen interface verbatim:
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
`analyze` calls `ngv2.pre_analysis.run_pre_analysis(repo_path, semgrep_finder=semgrep_finder, pattern_finder=pattern_finder, now_fn=now_fn)` and converts the `cross_validated`/`semgrep_only`/`scanner_only` buckets (in that order) into `Finding` objects with the id/target/category/severity/title/description/evidence mapping specified in the scope, each passing `.validate()`, deterministic and stable-ordered.
