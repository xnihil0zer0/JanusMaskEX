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
DEFAULT_TAINT_SPECS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'ngv2', 'taint_specs')

def _dedup_key(finding: Dict[str, Any]) -> Any:
    cwe = finding.get('cwe')
    cwe_key = tuple(cwe) if isinstance(cwe, (list, tuple)) else cwe
    return (finding.get('file', ''), finding.get('line', 0), finding.get('rule_id', ''), cwe_key)

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

def analyze_repo(clone_path: str, language: str, runner, *, pass_token: str, owner: str, repo: str, repo_sha: Optional[str]=None, db_cache: Optional[Dict[str, str]]=None, taint_specs_dir: Optional[str]=None) -> List[Dict[str, Any]]:
    """Run CodeQL over ``clone_path`` and return deduped findings.

    Refuses (``PermissionError``) unless ``pass_token`` authorises ``owner/repo``.
    Builds (or reuses, via ``db_cache`` keyed by ``repo@sha``) a database, runs
    the security-extended suite plus every bundled taint spec, and dedups by
    ``(file, line, rule_id, cwe)``. Findings carry a ``query_source`` tag.
    """
    if not verify_pass_token(pass_token, owner, repo):
        raise PermissionError('CodeQL refused: no valid preflight token for %s/%s' % (owner, repo))
    specs_dir = taint_specs_dir or DEFAULT_TAINT_SPECS_DIR
    cache_key = '%s/%s@%s' % (owner, repo, repo_sha) if repo_sha else None
    if db_cache is not None and cache_key is not None and (cache_key in db_cache):
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