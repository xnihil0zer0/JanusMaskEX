"""ngv2.portfolio_scanner -- pure, deterministic portfolio static scanner.

Classifies a directory of markdown findings files by huntr eligibility and
detects orphaned poc/test/submission artifacts. The module is PURE and
stdlib-only: the eligibility repo-set is injected (no network fallback) and the
scan clock is injected (``now=`` datetime) so results are deterministic.
"""
from __future__ import annotations
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Union
__all__ = ['ELIGIBLE_ENTRY_FIELDS', 'SCAN_RESULT_KEYS', 'extract_repo_from_findings', 'extract_finding_count_and_titles', 'extract_task_number', 'find_associated_files', 'scan']
PathLike = Union[Path, str]
ELIGIBLE_ENTRY_FIELDS: Tuple[str, ...] = ('repo', 'findings_file', 'task_number', 'poc_files', 'test_files', 'submission_files', 'finding_count', 'finding_titles')
SCAN_RESULT_KEYS: Tuple[str, ...] = ('scan_date', 'eligible', 'not_eligible', 'orphaned_pocs', 'orphaned_tests', 'orphaned_submissions')
_REPO_LINE_RE = re.compile('^\\s*\\*{0,2}(Target|Repository)\\*{0,2}\\s*:\\s*(?P<value>.+?)\\s*$', re.IGNORECASE)
_GITHUB_PREFIX_RE = re.compile('^(?:https?://)?(?:www\\.)?github\\.com/', re.IGNORECASE)
_FINDING_HEADER_RE = re.compile('^#{2,6}\\s+(?:Finding\\s+\\d+|[A-Za-z][A-Za-z0-9]*-\\d+)\\s*:\\s*(?P<title>.+?)\\s*$')
_TASK_NUMBER_RE = re.compile('^(?:task_)?(?P<num>\\d+)')

def _read_text(filepath: PathLike) -> Optional[str]:
    """Return the text content of *filepath*, or None if it cannot be read."""
    try:
        with open(os.fspath(filepath), 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except (OSError, ValueError):
        return None

def extract_repo_from_findings(filepath: PathLike) -> Optional[str]:
    """Extract a lowercased ``owner/repo`` from a findings file.

    Parses ``**Target**:`` lines (preferred) or ``**Repository**:`` lines,
    strips any leading github URL, and lowercases the result. Returns None when
    the file is missing or contains no such declaration.
    """
    text = _read_text(filepath)
    if text is None:
        return None
    target_value: Optional[str] = None
    repository_value: Optional[str] = None
    for line in text.splitlines():
        match = _REPO_LINE_RE.match(line)
        if not match:
            continue
        label = match.group(1).lower()
        value = match.group('value').strip()
        if label == 'target' and target_value is None:
            target_value = value
        elif label == 'repository' and repository_value is None:
            repository_value = value
    raw = target_value if target_value is not None else repository_value
    if not raw:
        return None
    cleaned = _GITHUB_PREFIX_RE.sub('', raw).strip().strip('/')
    if not cleaned:
        return None
    return cleaned.lower()

def extract_finding_count_and_titles(filepath: PathLike) -> Tuple[int, List[str]]:
    """Count findings headers in *filepath* and collect their titles.

    Recognizes ``### Finding N: <title>`` and ``### PREFIX-N: <title>`` headers.
    Returns ``(0, [])`` when the file is missing.
    """
    text = _read_text(filepath)
    if text is None:
        return (0, [])
    titles: List[str] = []
    for line in text.splitlines():
        match = _FINDING_HEADER_RE.match(line)
        if match:
            titles.append(match.group('title').strip())
    return (len(titles), titles)

def extract_task_number(filename: str) -> Optional[str]:
    """Extract the leading task number from *filename*.

    Handles both ``task_NNN_...`` and ``NNN_...`` forms. Returns None when no
    leading numeric prefix is present.
    """
    base = os.path.basename(str(filename))
    match = _TASK_NUMBER_RE.match(base)
    if not match:
        return None
    return match.group('num')

def _dedupe_preserve_order(items: List[str]) -> List[str]:
    """Return *items* with duplicates removed, preserving first-seen order."""
    seen = set()
    result: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

def _normalize_name(value: str) -> str:
    """Lowercase *value* and drop ``-``/``_`` separators for fuzzy matching."""
    return value.lower().replace('-', '').replace('_', '')

def _strict_matches(task_num: str, paths: List[str]) -> List[str]:
    """Return paths whose leading task number equals *task_num*, in order."""
    return [p for p in paths if extract_task_number(os.path.basename(p)) == task_num]

def _shortname_matches(short_norm: str, paths: List[str]) -> List[str]:
    """Return paths whose normalized basename contains *short_norm*, in order."""
    return [p for p in paths if short_norm in _normalize_name(os.path.basename(p))]

def find_associated_files(task_num: Optional[str], repo_name: str, all_pocs: List[str], all_tests: List[str], all_subs: List[str]) -> Tuple[List[str], List[str], List[str]]:
    """Associate poc/test/submission files with a task.

    Files are matched strictly by their leading task number. For early tasks
    (number < 100) with no strict match in a category, falls back to a repo
    short-name match: the repo basename, with ``-``/``_`` removed, must be at
    least 5 chars and appear in the file's normalized basename. Duplicates are
    filtered out and input order is strictly preserved.
    """
    if task_num is None:
        return ([], [], [])
    try:
        numeric = int(task_num)
    except (TypeError, ValueError):
        numeric = None
    short_norm: Optional[str] = None
    if numeric is not None and numeric < 100:
        short = (repo_name or '').split('/')[-1]
        candidate = _normalize_name(short)
        if len(candidate) >= 5:
            short_norm = candidate

    def _associate(paths: List[str]) -> List[str]:
        strict = _strict_matches(task_num, paths)
        if not strict and short_norm is not None:
            strict = _shortname_matches(short_norm, paths)
        return _dedupe_preserve_order(strict)
    return (_associate(all_pocs), _associate(all_tests), _associate(all_subs))

def _list_files(directory: PathLike, suffix: Optional[str]=None) -> List[str]:
    """Return sorted-by-name absolute file paths in *directory*.

    Missing directories are treated as empty. When *suffix* is given, only files
    ending with it are returned.
    """
    path = Path(directory)
    try:
        entries = [p for p in path.iterdir() if p.is_file()]
    except (OSError, ValueError):
        return []
    if suffix is not None:
        entries = [p for p in entries if p.name.endswith(suffix)]
    entries.sort(key=lambda p: p.name)
    return [str(p) for p in entries]

def scan(findings_dir: PathLike, poc_dir: PathLike, tests_dir: PathLike, subs_dir: PathLike, bounties_repos: set, now: datetime=None) -> dict:
    """Reconcile a portfolio of findings/poc/test/submission folders.

    Walks the findings directory, classifying each file as ``eligible`` or
    ``not_eligible`` based on whether its repo is in *bounties_repos*, links the
    associated poc/test/submission artifacts, and reports any artifacts that
    could not be associated as orphaned. Missing directories are treated as
    empty. The scan clock is injected via *now* for determinism.
    """
    eligible_repos = set(bounties_repos or set())
    findings_files = _list_files(findings_dir, suffix='.md')
    all_pocs = _list_files(poc_dir)
    all_tests = _list_files(tests_dir)
    all_subs = _list_files(subs_dir)
    eligible: dict = {}
    not_eligible: dict = {}
    used_pocs = set()
    used_tests = set()
    used_subs = set()
    for findings_file in findings_files:
        base = os.path.basename(findings_file)
        task_num = extract_task_number(base)
        repo = extract_repo_from_findings(findings_file)
        finding_count, finding_titles = extract_finding_count_and_titles(findings_file)
        poc_files, test_files, submission_files = find_associated_files(task_num, repo or '', all_pocs, all_tests, all_subs)
        used_pocs.update(poc_files)
        used_tests.update(test_files)
        used_subs.update(submission_files)
        entry = {'repo': repo, 'findings_file': findings_file, 'task_number': task_num, 'poc_files': poc_files, 'test_files': test_files, 'submission_files': submission_files, 'finding_count': finding_count, 'finding_titles': finding_titles}
        key = 'task_%s' % task_num if task_num is not None else os.path.splitext(base)[0]
        if repo is not None and repo in eligible_repos:
            eligible[key] = entry
        else:
            not_eligible[key] = entry
    orphaned_pocs = [p for p in all_pocs if p not in used_pocs]
    orphaned_tests = [p for p in all_tests if p not in used_tests]
    orphaned_submissions = [p for p in all_subs if p not in used_subs]
    return {'scan_date': now.isoformat() if now is not None else None, 'eligible': eligible, 'not_eligible': not_eligible, 'orphaned_pocs': orphaned_pocs, 'orphaned_tests': orphaned_tests, 'orphaned_submissions': orphaned_submissions}