"""Pure CorpusStats analytics over the huntr snapshots + PoC ground-truth.

This module is intentionally side-effect free: it reads only the dicts handed to
it plus the markdown files under ``poc_dir``. No network, no clock, no
randomness, no snapshot writes. It never raises on empty or malformed inputs.

Heavy lifting is delegated to existing siblings:
    * ``ngv2.title_cwe_classifier.classify_title`` -> per-title CWE label.
    * ``ngv2.prioritize.expected_payout``          -> per-repo payout math.
"""
from __future__ import annotations
import dataclasses
import os
import re
from typing import Dict, Tuple
from ngv2.prioritize import expected_payout
from ngv2.title_cwe_classifier import classify_title
_SCANNABLE_CONFIRMABLE = ('CWE-78', 'CWE-502')
_SCANNABLE_ONLY: Tuple[str, ...] = ()
_BASE_CWES = ('CWE-78', 'CWE-502', 'CWE-918', 'CWE-22')
_UNHEALTHY_MARKERS = ('$0', 'paused', 'inactive', 'no pool', 'closed')
_HEALTHY_MARKERS = ('active', 'well-funded', 'well funded', 'funded')
_CWE_RE = re.compile('CWE-(\\d+)', re.IGNORECASE)

@dataclasses.dataclass
class CorpusStats:
    """Aggregated, read-only view over the bounty corpus."""
    saturation: Dict[Tuple[str, str], float]
    expected_value: Dict[str, float]
    program_health: Dict[str, str]
    pipeline_capability: Dict[str, str]

def _capability_for(cwe: str) -> str:
    """Map a CWE to its fixed pipeline capability tier."""
    if cwe in _SCANNABLE_CONFIRMABLE:
        return 'scannable+confirmable'
    if cwe in _SCANNABLE_ONLY:
        return 'scannable'
    return 'none'

def _program_health_from_note(pool_note: object) -> str:
    """Parse a coarse program-health label out of a repo's pool_note."""
    if not isinstance(pool_note, str):
        return 'unknown'
    text = pool_note.strip().lower()
    if not text:
        return 'unknown'
    if any((marker in text for marker in _UNHEALTHY_MARKERS)):
        return 'at_risk'
    if any((marker in text for marker in _HEALTHY_MARKERS)):
        return 'healthy'
    return 'unknown'

def _classify(title: object) -> str:
    """Best-effort CWE label for a title; '' when unclassifiable."""
    if not isinstance(title, str):
        return ''
    label = classify_title(title)
    return label if isinstance(label, str) else ''

def _poc_ground_truth_cwes(poc_dir: str) -> set:
    """Read CWE labels declared in the PoC markdown ground-truth.

    Honours both inline ``CWE-NNN:`` lines and the ``### 5. CWE`` section shape.
    Returns an empty set for a missing directory or files without CWE markers.
    """
    found: set = set()
    if not isinstance(poc_dir, str) or not os.path.isdir(poc_dir):
        return found
    for root, _dirs, files in os.walk(poc_dir):
        for name in files:
            if not name.lower().endswith('.md'):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    text = handle.read()
            except OSError:
                continue
            for match in _CWE_RE.finditer(text):
                found.add('CWE-' + match.group(1))
    return found

def compute_corpus_stats(repo_bounties: dict, existing_submissions: dict, poc_dir: str) -> CorpusStats:
    """Compute a pure :class:`CorpusStats` over the provided snapshots.

    Args:
        repo_bounties: full huntr_repo_bounties.json snapshot
            (``{"repos": {"owner/repo": {...}}}``).
        existing_submissions: full huntr_existing_submissions.json snapshot
            (``{"owner/repo": {"titles": [...], ...}}``).
        poc_dir: directory of ``<repo>/<id>_submission.md`` PoC ground-truth.
    """
    repos = {}
    if isinstance(repo_bounties, dict):
        candidate = repo_bounties.get('repos')
        if isinstance(candidate, dict):
            repos = candidate
    saturation: Dict[Tuple[str, str], float] = {}
    observed_cwes: set = set()
    if isinstance(existing_submissions, dict):
        for repo, record in existing_submissions.items():
            if not isinstance(repo, str) or not isinstance(record, dict):
                continue
            titles = record.get('titles')
            if not isinstance(titles, list):
                continue
            for title in titles:
                cwe = _classify(title)
                if not cwe:
                    continue
                observed_cwes.add(cwe)
                pair = (repo, cwe)
                saturation[pair] = saturation.get(pair, 0.0) + 1.0
    expected_value: Dict[str, float] = {}
    program_health: Dict[str, str] = {}
    for repo, record in repos.items():
        if not isinstance(repo, str) or not isinstance(record, dict):
            continue
        raw_payout = expected_payout(record, 'critical')
        if isinstance(raw_payout, bool) or not isinstance(raw_payout, (int, float)):
            raw_payout = 0.0
        expected_value[repo] = float(raw_payout)
        program_health[repo] = _program_health_from_note(record.get('pool_note'))
    poc_cwes = _poc_ground_truth_cwes(poc_dir)
    all_cwes = set(_BASE_CWES) | observed_cwes | poc_cwes
    pipeline_capability: Dict[str, str] = {cwe: _capability_for(cwe) for cwe in sorted(all_cwes)}
    return CorpusStats(saturation=saturation, expected_value=expected_value, program_health=program_health, pipeline_capability=pipeline_capability)
