"""_e2e_run/drive_reachability.py -- the live reachability-cascade driver.

HAND-AUTHORED (not a blind-dispatch leaf): this is the integration glue that
runs the whole Phase-III cascade over a corpus, on the live hunt path. It is the
seam that makes the revived orphans actually fire end-to-end. Authored/edited by
the owner or agent AFTER Epics A/B/C land; verified by a smoke run on one cloned
repo (no unit oracle -- it is wiring).

Flow per cloned eligible repo:

    1. preflight (codeql_preflight)  -- refuse non-GitHub / non-OSI (token)
    2. prefilter (source_sink_prefilter) -- skip repos with no source x sink pair
    3. CodeQL    (codeql_orchestrate over make_subprocess_runner) -- prove paths
    4. proofs    (taint_path_signal) -- CodeQL findings -> taint_flow proofs
    5. triage    (session_gate ('triage','verify') with the llm seam + path)
       -> ADMIT candidates carry their source->sink path to the existing
          PoC writer / bwrap detonator (unchanged, already proven on gptcache).

This skeleton is intentionally minimal; it injects the real seams that the unit
oracles stub. Do NOT import it from ngv2/** production modules.
"""
from __future__ import annotations
import json
import subprocess
from typing import Any, Dict, Iterable, List

from ngv2.codeql_preflight import preflight
from ngv2.source_sink_prefilter import prefilter
from ngv2.codeql_orchestrate import analyze_repo
from ngv2.codeql_runner import make_subprocess_runner
from ngv2.taint_path_signal import proofs_from_findings
from ngv2.session_gate import gate_transition


def _gh_license_fetcher(owner: str, repo: str) -> Dict[str, Any] | None:
    """Live GitHub license lookup via the gh CLI (read-only)."""
    try:
        out = subprocess.run(
            ['gh', 'api', 'repos/%s/%s/license' % (owner, repo)],
            capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except Exception:
        return None


def drive_repo(target: Any, clone_path: str, *, language: str = 'python',
               codeql_bin: str = 'codeql', llm_complete=None,
               db_cache: Dict[str, str] | None = None) -> Dict[str, Any]:
    """Run the cascade for one cloned repo; return ADMIT candidates + trace."""
    trace: Dict[str, Any] = {'target': target, 'stage': None, 'candidates': []}

    pf = preflight(target, _gh_license_fetcher)
    trace['stage'] = 'preflight'
    if not pf.authorized:
        trace['refused'] = pf.reason
        return trace

    gate = prefilter(clone_path)
    trace['stage'] = 'prefilter'
    if not gate['keep']:
        trace['skipped'] = 'no source x sink pair'
        return trace
    trace['mode'] = gate['mode']

    runner = make_subprocess_runner(codeql_bin)
    findings = analyze_repo(clone_path, language, runner, pass_token=pf.token,
                            owner=pf.owner, repo=pf.repo, db_cache=db_cache)
    proofs = proofs_from_findings(findings)
    trace['stage'] = 'codeql'
    trace['taint_proofs'] = len(proofs)

    candidates: List[Dict[str, Any]] = []
    for proof in proofs:
        ev = {'finding': {'cwe': proof.get('cwe'), 'file': proof.get('file'),
                          'line': proof.get('line')},
              'taint_path': proof.get('path'), 'taint_proofs': [proof],
              'llm_complete': llm_complete}
        result = gate_transition('triage', 'verify', ev)
        if result.error not in ('out_of_scope', 'manual_review_scope'):
            candidates.append({'proof': proof, 'gate': result.error or 'admit'})
    trace['stage'] = 'triage'
    trace['candidates'] = candidates
    # -> hand candidates (with path) to the existing PoC writer / detonator.
    return trace


def drive_corpus(repos: Iterable[Dict[str, Any]], **kw) -> List[Dict[str, Any]]:
    """Run drive_repo over a corpus of {target, clone_path} entries."""
    db_cache: Dict[str, str] = {}
    return [drive_repo(r['target'], r['clone_path'], db_cache=db_cache, **kw)
            for r in repos]
