---
interfaces: "creates NEW ngv2/codeql_orchestrate.py exposing analyze_repo(clone_path, language, runner, *, pass_token, owner, repo, repo_sha, db_cache, taint_specs_dir)->findings — Stage-2 glue that enforces the preflight token, builds/caches a DB, runs security-extended + bundled specs, and dedups"
dependencies: ["ngv2_codeql_runner_subprocess_factory", "ngv2_codeql_preflight"]
meta_task_type: data_model
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/codeql_orchestrate.py — NEW Stage-2 CodeQL orchestration over the injected runner seam: license-token-gated create_database → security-extended suite → bundled taint specs → deduped findings.

# Scope

CREATE the NEW single-file module `ngv2/codeql_orchestrate.py`. `analyze_repo` REFUSES (PermissionError) unless handed a `pass_token` that `ngv2.codeql_preflight.verify_pass_token` accepts for owner/repo — so an unlicensed/non-GitHub target can never reach a DB build (owner condition). It then builds (or reuses, via a `db_cache` keyed by repo@sha) a database through the injected runner from `ngv2.codeql_runner`, runs the security-extended suite plus every bundled `data/ngv2/taint_specs/*.ql` spec (validated via `ngv2.taint_spec_library.load_taint_spec_manifest`), and dedups by (file,line,rule_id,cwe). PURE w.r.t. the environment — it NEVER spawns codeql itself (every call goes through the injected `runner` seam).

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): NEW single-file module, emit the COMPLETE file for `ngv2/codeql_orchestrate.py` BYTE-FOR-BYTE:

```python
"""ngv2.codeql_orchestrate -- thin CodeQL Stage-2 orchestration over the runner.

Glue that turns a clone path into deduped CodeQL findings:

    create_database -> run security-extended suite -> run each bundled taint spec
    (data/ngv2/taint_specs/*.ql, validated via taint_spec_library) -> dedup.

It is PURE with respect to the environment: every CodeQL call goes through the
injected ``runner`` seam from ``ngv2.codeql_runner`` (the oracle scripts it; the
live path injects ``make_subprocess_runner``). It NEVER spawns codeql itself.

License enforcement (owner condition): ``analyze_repo`` refuses to build a
database unless it is handed a ``pass_token`` that
``ngv2.codeql_preflight.verify_pass_token`` accepts for ``owner/repo`` -- so an
unlicensed / non-GitHub target can never reach a CodeQL DB build. A simple
``db_cache`` keyed by ``repo@sha`` avoids rebuilding the same database.

Stdlib-only; no clock, randomness, network, or subprocess at module scope.
"""
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional

from ngv2.codeql_runner import create_database, run_security_queries, run_custom_spec
from ngv2.codeql_preflight import verify_pass_token

__all__ = ['analyze_repo', 'DEFAULT_TAINT_SPECS_DIR']

DEFAULT_TAINT_SPECS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'ngv2', 'taint_specs')


def _dedup_key(finding: Dict[str, Any]) -> Any:
    cwe = finding.get('cwe')
    cwe_key = tuple(cwe) if isinstance(cwe, (list, tuple)) else cwe
    return (finding.get('file', ''), finding.get('line', 0),
            finding.get('rule_id', ''), cwe_key)


def _load_spec_paths(taint_specs_dir: str) -> List[str]:
    """Return validated ``.ql`` spec paths in manifest order; [] on any error."""
    try:
        from ngv2.taint_spec_library import load_taint_spec_manifest
        entries = load_taint_spec_manifest(taint_specs_dir)
    except Exception:
        return []
    paths = []
    for entry in entries:
        ql = entry.get('file') if isinstance(entry, dict) else None
        if ql:
            paths.append(os.path.join(taint_specs_dir, ql))
    return paths


def analyze_repo(clone_path: str, language: str, runner, *, pass_token: str,
                 owner: str, repo: str, repo_sha: Optional[str] = None,
                 db_cache: Optional[Dict[str, str]] = None,
                 taint_specs_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Run CodeQL over ``clone_path`` and return deduped findings.

    Refuses (``PermissionError``) unless ``pass_token`` authorises ``owner/repo``.
    Builds (or reuses, via ``db_cache`` keyed by ``repo@sha``) a database, runs
    the security-extended suite plus every bundled taint spec, and dedups by
    ``(file, line, rule_id, cwe)``. Findings carry a ``query_source`` tag.
    """
    if not verify_pass_token(pass_token, owner, repo):
        raise PermissionError(
            'CodeQL refused: no valid preflight token for %s/%s' % (owner, repo))
    specs_dir = taint_specs_dir or DEFAULT_TAINT_SPECS_DIR
    cache_key = '%s/%s@%s' % (owner, repo, repo_sha) if repo_sha else None
    if db_cache is not None and cache_key is not None and cache_key in db_cache:
        database = db_cache[cache_key]
    else:
        database = create_database(clone_path, language, runner)
        if db_cache is not None and cache_key is not None:
            db_cache[cache_key] = database

    merged: List[Dict[str, Any]] = []
    seen = set()

    def _absorb(findings: List[Dict[str, Any]], source: str) -> None:
        for finding in findings or []:
            if not isinstance(finding, dict) or 'error' in finding:
                continue
            key = _dedup_key(finding)
            if key in seen:
                continue
            seen.add(key)
            tagged = dict(finding)
            tagged.setdefault('query_source', source)
            merged.append(tagged)

    _absorb(run_security_queries(database, language, runner), 'security-extended')
    for spec_path in _load_spec_paths(specs_dir):
        _absorb(run_custom_spec(database, spec_path, runner), os.path.basename(spec_path))

    merged.sort(key=lambda f: (f.get('file', ''), f.get('line', 0), f.get('rule_id', '')))
    return merged
```

POST-EMIT SELF-CHECK (mandatory): analyze_repo raises PermissionError before any create when the token is invalid; merged findings are deduped and sorted; specs are loaded via load_taint_spec_manifest; no direct subprocess/codeql spawn.

# Required plan shape

EXACTLY ONE impl task. task_id VERBATIM: `ngv2_codeql_orchestrate`. meta_task_type=`data_model`. priority: high. dependencies: ["ngv2_codeql_runner_subprocess_factory", "ngv2_codeql_preflight"]. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/codeql_orchestrate.py"]` ONLY. partial_edit: WHOLE-FILE — copy the DISPATCH DIRECTIVE block VERBATIM into `implementation_notes`. verification_command: `python3 -m pytest -q tests/ngv2/test_codeql_orchestrate_wired.py` (CWD-relative — NO `cd`). Make the committed RED oracle tests/ngv2/test_codeql_orchestrate_wired.py GREEN (3 tests); do NOT author tests. `test_spec.regression_tests` (≥2 named): `test_orchestrates_and_dedups_cwe502_path`, `test_db_cache_skips_rebuild_on_same_sha`. `test_spec.edge_cases` (≥2): `test_refuses_without_valid_token`, `test_db_cache_skips_rebuild_on_same_sha` — incl. integration-style `test_orchestrates_and_dedups_cwe502_path`.

# Non-Goals

Do NOT spawn the real codeql binary — the runner is injected (the live runner is codeql_runner.make_subprocess_runner, a separate leaf). Do NOT touch codeql_runner, codeql_preflight, or taint_spec_library. Do NOT add network, clock, randomness, or logging. Driver INTEGRATION feeding the cascade is a separate downstream leaf.

# Inputs

The committed oracle tests/ngv2/test_codeql_orchestrate_wired.py (RED — module absent). With an injected scripted runner (never real codeql) it pins: refusal without a valid token (PermissionError); create→security-suite→bundled-specs orchestration deduping a CWE-502 path to one finding tagged with query_source; and the repo@sha DB cache invoking create exactly once across two calls.

# Deliverables

The NEW file `ngv2/codeql_orchestrate.py` as pinned, GREEN by `python3 -m pytest -q tests/ngv2/test_codeql_orchestrate_wired.py` (3 passed).
