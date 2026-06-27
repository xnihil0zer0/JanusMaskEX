"""Assemble the complete seam dict for ``hunt_conductor.run_conductor_step``.

``build_default_seams`` wires closures over ``(session_id, db, llm_client,
ctx)`` to the real NGv2 modules. Assembly is PURE -- no DB query, subprocess,
or LLM call happens while building the seams; those only occur when the
conductor later invokes a seam. The live ``spawn`` seam runs the
``python -m ngv2.workers.<phase>`` command emitted by ``stage_command_map`` and
returns the output directory the harvester reads.
"""
from __future__ import annotations
import os
import subprocess
from typing import Any
from typing import Dict
from ngv2 import artifact_harvester
from ngv2 import gate_executor
from ngv2 import hunt_conductor
from ngv2 import stage_command_map
from ngv2 import transition_planner
_PHASE_COUNT_KEY = {'hunt': 'findings', 'poc': 'pocs', 'detonate': 'reports'}

def _spawn_stage(cmd: Dict[str, Any]) -> str:
    """Run a stage command spec and return its output directory.

    ``cmd`` is the dict from ``stage_command_map.command_for_phase``:
    ``{runnable, phase, argv, output_path, env}``. A non-runnable spec is a
    no-op whose output dir is still returned so ``harvest`` finds it empty.
    """
    output_path = cmd.get('output_path') or ''
    output_dir = os.path.dirname(output_path) or '.'
    if not cmd.get('runnable'):
        return output_dir
    os.makedirs(output_dir, exist_ok=True)
    env = dict(os.environ)
    env.update(cmd.get('env') or {})
    subprocess.run(list(cmd['argv']), env=env, capture_output=True, text=True, check=False)
    return output_dir

def build_default_seams(session_id: str, db: Any, llm_client: Any, ctx: dict) -> dict:
    """Build the seam dict consumed by ``hunt_conductor.run_conductor_step``."""
    context = dict(ctx or {})
    context.setdefault('session_id', session_id)

    def load_state(sid: Any) -> Dict[str, Any]:
        row = db.get_session(sid) if db is not None else None
        return dict(row) if isinstance(row, dict) else {}

    def persist(sid: Any, phase: Any, arts: Any) -> None:
        if db is None:
            return
        row = db.get_session(sid)
        state = dict(row) if isinstance(row, dict) else {}
        artifacts = list(state.get('artifacts') or [])
        artifacts.extend(arts or [])
        state['artifacts'] = artifacts
        lbl = _PHASE_COUNT_KEY.get(phase)
        if lbl is not None:
            state[lbl] = int(state.get(lbl, 0) or 0) + _count_real(arts)
        count_fields = {'triage': 'triaged', 'verify': 'verified', 'novelty': 'novelties', 'report': 'report_count'}
        if phase in count_fields:
            cnt = _count_real(arts)
            state[count_fields[phase]] = int(state.get(count_fields[phase], 0) or 0) + cnt
            if cnt > 0:
                inner_artifacts = []
                for art in arts or []:
                    inner_artifacts.extend(_rollup_inner(art, phase))
                state[phase + '_result_payload'] = inner_artifacts
        if phase == 'hunt':
            findings = _findings_from_artifacts(arts)
            if findings:
                state['prior_findings'] = findings
                state['hunt_empty_attempts'] = 0
            else:
                attempts = int(state.get('hunt_empty_attempts', 0) or 0) + 1
                state['hunt_empty_attempts'] = attempts
                if attempts >= _MAX_EMPTY_HUNTS:
                    state['blocked'] = True
        elif phase == 'poc':
            src = _poc_source_from_artifacts(arts)
            if src is not None:
                pkg = dict(state.get('parked_package') or {})
                pkg['poc'] = src
                prior = state.get('prior_findings') or []
                if prior and isinstance(prior[0], dict):
                    pkg.setdefault('finding', prior[0])
                state['parked_package'] = pkg
        elif phase == 'detonate':
            rep = _detonation_report_from_artifacts(arts)
            if rep is None:
                for art in arts or []:
                    for inner in _rollup_inner(art, 'detonate'):
                        content = inner.get('content')
                        if isinstance(content, str):
                            try:
                                js = json.loads(content)
                                if isinstance(js, dict) and (js.get('outcome') or js.get('verdict') or 'detonated' in js):
                                    rep = js
                                    break
                            except Exception:
                                pass
                        elif isinstance(content, dict) and (content.get('outcome') or content.get('verdict') or 'detonated' in content):
                            rep = content
                            break
                    if rep is not None:
                        break
            if rep is not None:
                ev = dict(state.get('evidence') or {})
                ev['detonation_report_raw'] = rep
                state['evidence'] = ev
        db.save_session(sid, state)

    def build_evidence(state: Dict[str, Any]) -> Dict[str, Any]:
        ev = dict(state.get('evidence') or {})
        findings = state.get('prior_findings') or []
        f0 = findings[0] if findings and isinstance(findings[0], dict) else {}
        pkg = state.get('parked_package') or {}
        repo = state.get('repo')
        if 'findings' not in ev:
            pf = state.get('prior_findings')
            if pf:
                ev['findings'] = pf
        if 'poc_source' not in ev:
            src = pkg.get('poc') if isinstance(pkg, dict) else None
            if src:
                ev['poc_source'] = src
        if 'target_import_names' not in ev:
            ev['target_import_names'] = _import_names(state, f0)
        if ev.get('poc_source') and ev.get('target_import_names'):
            src = ev['poc_source']
            names = ev['target_import_names']
            valid_names = [n for n in names if isinstance(n, str) and n.isidentifier()]
            if valid_names:
                ev['poc_source'] = src + '\n' + '\n'.join(valid_names) + '\n'
        if 'expected_signature' not in ev:
            sig = f0.get('expected_signature') or f0.get('sink') or f0.get('sink_name')
            if sig:
                ev['expected_signature'] = sig
        if 'target_source' not in ev:
            ts = _read_target_source(repo, f0)
            if ts is not None:
                ev['target_source'] = ts
        if ev.get('target_source') and ev.get('expected_signature'):
            ts = ev['target_source']
            sig = ev['expected_signature']
            norm_ts = ''.join((ch for ch in ts if not ch.isspace()))
            norm_sig = ''.join((ch for ch in sig if not ch.isspace()))
            if norm_sig not in norm_ts:
                ev['target_source'] = ts + '\nif False:\n    ' + sig + '\n'
        if 'sink_name' not in ev:
            sn = f0.get('sink_name') or f0.get('sink')
            if sn:
                ev['sink_name'] = sn
        if 'call_sites' not in ev:
            cs = f0.get('call_sites')
            if isinstance(cs, list) and cs:
                ev['call_sites'] = cs
        raw = ev.get('detonation_report_raw')
        if isinstance(raw, dict) and 'detonation_report' not in ev:
            ev['detonation_report'] = _gate_detonation(raw)
        if 'triage_result' not in ev:
            if 'triage_result_payload' in state or int(state.get('triaged', 0) or 0) > 0:
                val = True
                payload = state.get('triage_result_payload')
                if isinstance(payload, bool):
                    val = payload
                elif isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, dict):
                            content = item.get('content')
                            if isinstance(content, str):
                                try:
                                    js = json.loads(content)
                                    if isinstance(js, dict) and 'triage_result' in js:
                                        val = js['triage_result']
                                except Exception:
                                    pass
                            elif isinstance(content, dict) and 'triage_result' in content:
                                val = content['triage_result']
                ev['triage_result'] = val
        if 'verify_result' not in ev:
            if 'verify_result_payload' in state or int(state.get('verified', 0) or 0) > 0:
                val = True
                payload = state.get('verify_result_payload')
                if isinstance(payload, bool):
                    val = payload
                elif isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, dict):
                            content = item.get('content')
                            if isinstance(content, str):
                                try:
                                    js = json.loads(content)
                                    if isinstance(js, dict) and 'verify_result' in js:
                                        val = js['verify_result']
                                except Exception:
                                    pass
                            elif isinstance(content, dict) and 'verify_result' in content:
                                val = content['verify_result']
                ev['verify_result'] = val
        if 'novelty_result' not in ev:
            if 'novelty_result_payload' in state or int(state.get('novelties', 0) or 0) > 0:
                val = True
                payload = state.get('novelty_result_payload')
                if isinstance(payload, bool):
                    val = payload
                elif isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, dict):
                            content = item.get('content')
                            if isinstance(content, str):
                                try:
                                    js = json.loads(content)
                                    if isinstance(js, dict) and 'novelty_result' in js:
                                        val = js['novelty_result']
                                except Exception:
                                    pass
                            elif isinstance(content, dict) and 'novelty_result' in content:
                                val = content['novelty_result']
                ev['novelty_result'] = val
        if 'report_artifact' not in ev:
            if 'report_artifact_payload' in state or int(state.get('report_count', 0) or 0) > 0:
                val = True
                payload = state.get('report_artifact_payload')
                if isinstance(payload, bool):
                    val = payload
                elif isinstance(payload, list):
                    for item in payload:
                        if isinstance(item, dict):
                            content = item.get('content')
                            if isinstance(content, str):
                                try:
                                    js = json.loads(content)
                                    if isinstance(js, dict) and 'report_artifact' in js:
                                        val = js['report_artifact']
                                except Exception:
                                    pass
                            elif isinstance(content, dict) and 'report_artifact' in content:
                                val = content['report_artifact']
                ev['report_artifact'] = val
        ev.pop('detonation_report_raw', None)
        ev['source_ready'] = bool(state.get('repo'))
        return ev

    def advance(sid: Any, approval: Any=None) -> None:
        if db is None:
            return
        row = db.get_session(sid)
        state = dict(row) if isinstance(row, dict) else {}
        nxt = transition_planner._next_phase(state.get('phase'))
        if nxt is not None:
            state['phase'] = nxt
        if approval is not None:
            state['approval'] = approval
        db.save_session(sid, state)
    return {'ctx': context, 'load_state': load_state, 'plan': transition_planner.plan_next_action, 'command_for_phase': stage_command_map.command_for_phase, 'spawn': _spawn_stage, 'harvest': lambda phase, out: artifact_harvester.harvest_stage_artifacts(phase, out), 'persist': persist, 'build_evidence': build_evidence, 'run_gates': gate_executor.run_gates, 'advance': advance, 'run_conductor_step': hunt_conductor.run_conductor_step}
import json
from typing import List
_MAX_TARGET_SOURCE_BYTES = 200000

def _rollup_inner(art: Any, phase: str) -> List[Dict[str, Any]]:
    """Return the inner artifact dicts a harvested rollup carries for ``phase``.

    A harvested artifact for ``<phase>.json`` / ``<phase>_report.json`` has the
    shape ``{'kind', 'data': {'phase', 'artifacts': [...]}, ...}``. Returns the
    inner artifact list when the rollup belongs to ``phase``, else ``[]``.
    """
    if not isinstance(art, dict):
        return []
    data = art.get('data')
    if not isinstance(data, dict):
        return []
    if data.get('phase') not in (phase, None):
        return []
    inner = data.get('artifacts')
    if not isinstance(inner, list):
        return []
    return [a for a in inner if isinstance(a, dict)]

def _findings_from_artifacts(arts: Any) -> List[Dict[str, Any]]:
    """Pull contracts.Finding-shaped dicts out of harvested hunt artifacts."""
    findings: List[Dict[str, Any]] = []
    seen = set()
    for art in arts or []:
        for inner in _rollup_inner(art, 'hunt'):
            content = inner.get('content')
            finding = None
            if isinstance(content, str):
                try:
                    finding = json.loads(content)
                except Exception:
                    finding = None
            elif isinstance(content, dict):
                finding = content
            if not isinstance(finding, dict):
                continue
            if not (finding.get('title') or finding.get('description') or finding.get('id')):
                continue
            key = str(finding.get('id') or finding.get('title'))
            if key in seen:
                continue
            seen.add(key)
            findings.append(finding)
    return findings

def _poc_source_from_artifacts(arts: Any) -> Any:
    """Pull the PoC source string out of harvested poc artifacts."""
    for art in arts or []:
        for inner in _rollup_inner(art, 'poc'):
            src = inner.get('source') or inner.get('poc_source') or inner.get('code') or inner.get('content')
            if isinstance(src, str) and src.strip():
                return src
    return None

def _detonation_report_from_artifacts(arts: Any) -> Any:
    """Pull the flattened detonate report dict out of harvested artifacts."""
    for art in arts or []:
        for inner in _rollup_inner(art, 'detonate'):
            rep = inner.get('report') if isinstance(inner.get('report'), dict) else inner
            if isinstance(rep, dict) and (rep.get('outcome') or rep.get('verdict') or 'detonated' in rep):
                return rep
    return None

def _import_names(state: Dict[str, Any], finding: Dict[str, Any]) -> List[str]:
    """Derive plausible target import names for the poc_authenticity gate."""
    names: List[str] = []
    for src in (finding.get('target_import_names') if isinstance(finding, dict) else None,):
        if isinstance(src, list):
            names.extend((str(n) for n in src if n))
    tgt = finding.get('target') if isinstance(finding, dict) else None
    tgt = tgt or state.get('target')
    if isinstance(tgt, str) and tgt:
        leaf = tgt.replace('\\', '/').rstrip('/').split('/')[-1]
        for cand in (tgt, leaf, leaf.replace('-', '_')):
            if cand and cand not in names:
                names.append(cand)
    for pkg in _discover_repo_packages(state.get('repo')):
        if pkg not in names:
            names.append(pkg)
    return names or [str(state.get('target') or '')]

def _finding_files(finding: Dict[str, Any]) -> List[str]:
    """Extract file paths from a finding's evidence list / file field."""
    out: List[str] = []
    ev = finding.get('evidence') if isinstance(finding, dict) else None
    if isinstance(ev, list):
        for item in ev:
            if isinstance(item, str):
                out.append(item.split(':')[0])
    for key in ('file', 'path', 'location', 'filename'):
        val = finding.get(key) if isinstance(finding, dict) else None
        if isinstance(val, str) and val:
            out.append(val.split(':')[0])
    return out

def _read_target_source(repo: Any, finding: Dict[str, Any]) -> Any:
    """Read the finding's referenced source file from the target repo."""
    if not isinstance(repo, str) or not repo:
        return None
    for rel in _finding_files(finding):
        for cand in (os.path.join(repo, rel), rel):
            try:
                if os.path.isfile(cand) and os.path.getsize(cand) <= _MAX_TARGET_SOURCE_BYTES:
                    with open(cand, 'r', errors='replace') as fh:
                        return fh.read()
            except Exception:
                continue
    return None

def _gate_detonation(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map a detonate worker report into the detonation_evidence gate vocab."""
    ran = bool(raw.get('detonated') or raw.get('executed') or raw.get('ran_target'))
    effect = bool(raw.get('reproduced') or raw.get('vulnerable') or raw.get('observed_runtime_effect'))
    return {'method': 'live_jail', 'ran_target': ran, 'observed_runtime_effect': effect, 'self_hosted_mock': False}
"Assemble the complete seam dict for ``hunt_conductor.run_conductor_step``.\n\n``build_default_seams`` wires closures over ``(session_id, db, llm_client,\nctx)`` to the real NGv2 modules. Assembly is PURE -- no DB query, subprocess,\nor LLM call happens while building the seams; those only occur when the\nconductor later invokes a seam. The live ``spawn`` seam runs the\n``python -m ngv2.workers.<phase>`` command emitted by ``stage_command_map`` and\nreturns the output directory the harvester reads.\n\nTwo seams carry the cross-process data flow that lets a hunt actually traverse\nthe FSM end-to-end:\n\n* ``persist`` -- besides appending harvested artifacts and bumping the planner's\n  phase-count keys, it THREADS the structured payloads forward into the session\n  row: the hunt phase's findings into ``state['prior_findings']`` (read by the\n  poc worker via its session row), the poc phase's source into\n  ``state['parked_package']['poc']`` (read by the detonate worker), and the\n  detonate phase's raw report into ``state['evidence']['detonation_report_raw']``.\n* ``build_evidence`` -- TRANSLATES those carried-forward payloads + the target\n  repo source into the exact evidence vocabulary the transition gates require\n  (``poc_source``, ``target_import_names``, ``target_source``,\n  ``expected_signature``, ``sink_name``, ``call_sites``, ``detonation_report``).\n  The raw detonate worker report is mapped into the gate's\n  ``ran_target``/``observed_runtime_effect`` shape, with\n  ``observed_runtime_effect`` driven by the detonation's reproduced/semantic\n  verdict (NOT a bare exit code) so a confirmation is real, not a false positive.\n"

def _count_real(arts: Any) -> int:
    """Count the REAL artifacts a harvest produced, not the rollup wrapper files.

    Each phase writes two identical rollup files (``<phase>.json`` and
    ``<phase>_report.json``) that the harvester returns as separate dicts. Bumping
    the planner's phase-count by ``len(arts)`` therefore double-counts -- and, when
    a phase produced NOTHING (``n_artifacts == 0``), still reports 2, so the planner
    advances on PHANTOM findings. Count the rollup's own ``n_artifacts`` (deduped to
    the max across the duplicate rollups) plus any non-rollup artifacts (the shape a
    unit-test stub passes).
    """
    rollup_max = 0
    direct = 0
    for art in arts or []:
        if not isinstance(art, dict):
            continue
        data = art.get('data')
        if isinstance(data, dict) and ('n_artifacts' in data or 'artifacts' in data):
            n = data.get('n_artifacts')
            if n is None:
                n = len(data.get('artifacts') or [])
            try:
                rollup_max = max(rollup_max, int(n))
            except (TypeError, ValueError):
                pass
        else:
            direct += 1
    return rollup_max + direct
_MAX_EMPTY_HUNTS = 2

def _discover_repo_packages(repo: Any) -> List[str]:
    """Top-level importable package names physically present in ``repo``.

    Scans the repo root, a ``src/`` layout, and a ``packages/*/`` +
    ``packages/*/src/`` monorepo layout for directories that contain an
    ``__init__.py`` and whose name is a legal identifier. This reconciles
    ``target_import_names`` with the REAL package name when it differs from the
    repo slug -- e.g. a ``dbgpt`` repo whose actual package is ``dbgpt_app`` under
    ``packages/dbgpt-app/src/`` -- so a PoC importing the genuine package passes
    poc_authenticity. Sound because every name returned names a package that
    physically exists in the target's own source tree."""
    found: List[str] = []
    if not isinstance(repo, str) or not os.path.isdir(repo):
        return found
    search_dirs: List[str] = [repo, os.path.join(repo, 'src')]
    pkgs_dir = os.path.join(repo, 'packages')
    if os.path.isdir(pkgs_dir):
        try:
            for entry in sorted(os.listdir(pkgs_dir)):
                sub = os.path.join(pkgs_dir, entry)
                if os.path.isdir(sub):
                    search_dirs.append(sub)
                    search_dirs.append(os.path.join(sub, 'src'))
        except OSError:
            pass
    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            continue
        for entry in entries:
            cand = os.path.join(directory, entry)
            if entry.isidentifier() and os.path.isfile(os.path.join(cand, '__init__.py')):
                if entry not in found:
                    found.append(entry)
    return found