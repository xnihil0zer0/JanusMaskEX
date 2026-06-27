"""Deterministic submission-file parser for NobleGreed v2.

Turns submission-ready markdown into structured :class:`FindingSubmission`
records, normalizes vulnerability-type labels, and extracts (possibly nested)
fenced code blocks. All non-deterministic behaviour (network, clock,
Playwright form-filling) is intentionally absent: the queue scanner takes an
injected root directory so it is fully deterministic.

Imports are restricted to ``re``, ``dataclasses`` and ``pathlib`` (plus
``ngv2.contracts`` spine types where required by the oracle -- not needed
here). The module performs no real network, clock, subprocess, LLM/model,
GPU, Playwright or MCP activity.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
CVSS_DIM_ORDER: List[str] = ['AV', 'AC', 'PR', 'UI', 'S', 'C', 'I', 'A']
VULN_TYPE_MAP: Dict[str, str] = {'code injection': 'Code Injection', 'cwe-94': 'Code Injection', 'ssrf': 'Server Side Request Forgery (SSRF)', 'server side request forgery (ssrf)': 'Server Side Request Forgery (SSRF)', 'cwe-918': 'Server Side Request Forgery (SSRF)', 'deserialization of untrusted data': 'Deserialization of Untrusted Data', 'cwe-502': 'Deserialization of Untrusted Data', 'cross-site scripting (xss)': 'Cross-Site Scripting (XSS)', 'xss': 'Cross-Site Scripting (XSS)', 'cwe-79': 'Cross-Site Scripting (XSS)', 'path traversal': 'Path Traversal', 'cwe-22': 'Path Traversal'}

@dataclass
class FindingSubmission:
    """A single structured vulnerability finding parsed from markdown."""
    finding_id: str = ''
    title: str = ''
    repo_url: str = ''
    package_manager: str = 'pypi'
    version: str = ''
    vuln_type: str = ''
    cwe: str = ''
    cvss_vector: str = ''
    description: str = ''
    poc_code: str = ''
    severity: str = ''
    source_file: str = ''
    expected_bounty: float = 0.0

    def cvss_components(self) -> Dict[str, str]:
        """Parse ``cvss_vector`` into a ``{dimension: value}`` mapping.

        Only dimensions present in :data:`CVSS_DIM_ORDER` are kept.
        """
        comps: Dict[str, str] = {}
        for part in self.cvss_vector.split('/'):
            if ':' not in part:
                continue
            dim, _, val = part.partition(':')
            dim = dim.strip()
            if dim in CVSS_DIM_ORDER:
                comps[dim] = val.strip()
        return comps

    def validate(self) -> List[str]:
        """Return a list of human-readable validation error strings."""
        errs: List[str] = []
        if not self.title.strip():
            errs.append('missing title')
        repo = self.repo_url.strip()
        if not repo:
            errs.append('missing repo_url')
        elif not re.match('https?://(www\\.)?github\\.com/.+', repo):
            errs.append('invalid repo_url: ' + repo)
        if not self.version.strip():
            errs.append('missing version')
        if not self.vuln_type.strip():
            errs.append('missing vuln_type')
        if not self.description.strip():
            errs.append('missing description')
        if self.cvss_vector.strip():
            comps = self.cvss_components()
            missing = [d for d in CVSS_DIM_ORDER if d not in comps]
            if missing:
                errs.append('CVSS vector missing dims: ' + ', '.join(missing))
        return errs

def _normalize_vuln_type(raw: str) -> str:
    """Map a raw vulnerability label onto its canonical form.

    Resolution order: exact (case/whitespace-insensitive) alias, embedded
    ``CWE-<n>`` identifier, then a title-cased fallback of the raw input.
    """
    if not raw:
        return ''
    text = raw.strip()
    if not text:
        return ''
    low = text.lower()
    if low in VULN_TYPE_MAP:
        return VULN_TYPE_MAP[low]
    m = re.search('cwe[-\\s]?(\\d+)', low)
    if m:
        cwe_id = 'cwe-' + m.group(1)
        if cwe_id in VULN_TYPE_MAP:
            return VULN_TYPE_MAP[cwe_id]
    return text.title()

def _extract_cwe(text: str) -> str:
    """Return a normalized ``CWE-<n>`` token found in *text* (or '')."""
    m = re.search('cwe[-\\s]?(\\d+)', text, re.IGNORECASE)
    return 'CWE-' + m.group(1) if m else ''

def _normalize_repo_url(value: str) -> str:
    """Normalize a repository reference into a full URL.

    Owner/repo shorthand (``acme/service``) is expanded to a github URL;
    values that already look like URLs are returned unchanged.
    """
    value = value.strip().strip('`').strip()
    if not value:
        return ''
    if value.startswith('http://') or value.startswith('https://'):
        return value
    return 'https://github.com/' + value.lstrip('/')

def _parse_money(text: str) -> float:
    """Parse a currency-ish string (``$5,000``) into a float."""
    cleaned = re.sub('[^\\d.]', '', text or '')
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def _extract_code_block(text: str, start: int) -> Tuple[str, int]:
    """Extract the first fenced code block at/after *start*.

    Returns ``(content, end)`` where *content* is the text strictly between
    the opening and closing fences (preserving inner newlines and any nested
    fences) and *end* is the index just past the closing fence line. If no
    opening fence is found, returns ``('', start)``. If the block is never
    closed, the remainder of the text is returned with ``end == len(text)``.
    """
    n = len(text)
    pos = start
    content_start: Optional[int] = None
    while pos <= n:
        nl = text.find('\n', pos)
        line_end = n if nl == -1 else nl
        line = text[pos:line_end]
        if line.lstrip().startswith('```'):
            content_start = n if nl == -1 else nl + 1
            break
        if nl == -1:
            break
        pos = nl + 1
    if content_start is None:
        return ('', start)
    depth = 1
    pos = content_start
    while pos < n:
        nl = text.find('\n', pos)
        line_end = n if nl == -1 else nl
        stripped = text[pos:line_end].strip()
        if stripped.startswith('```'):
            after = stripped[3:].strip()
            if after:
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    end = n if nl == -1 else nl + 1
                    return (text[content_start:pos], end)
        if nl == -1:
            break
        pos = nl + 1
    return (text[content_start:n], n)

def _field_a(block: str, label: str) -> str:
    """Extract a ``**Label:** value`` (optionally backtick-wrapped) field."""
    pattern = '\\*\\*\\s*' + re.escape(label) + '\\s*:?\\s*\\*\\*\\s*:?\\s*`?([^\\n`]*)`?'
    m = re.search(pattern, block, re.IGNORECASE)
    return m.group(1).strip() if m else ''

def _inline_bold(text: str, label: str) -> str:
    """Extract a ``**Label**: value`` inline field."""
    pattern = '\\*\\*\\s*' + re.escape(label) + '\\s*\\*\\*\\s*:?\\s*`?([^\\n`]*)`?'
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else ''

def _section_body(text: str, name: str) -> str:
    """Return the body of a ``## <name>`` markdown section (or '')."""
    head = re.search('^##\\s*' + re.escape(name) + '\\s*$', text, re.IGNORECASE | re.MULTILINE)
    if not head:
        return ''
    start = head.end()
    nxt = re.search('^##\\s', text[start:], re.MULTILINE)
    end = start + nxt.start() if nxt else len(text)
    return text[start:end].strip()

def _parse_format_a(text: str) -> List[FindingSubmission]:
    """Parse the multi-finding ``## FINDING N -- title`` format."""
    findings: List[FindingSubmission] = []
    heading_re = re.compile('^##\\s*FINDING\\b.*$', re.IGNORECASE | re.MULTILINE)
    matches = list(heading_re.finditer(text))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]
        f = FindingSubmission()
        lines = block.splitlines()
        heading_line = lines[0] if lines else ''
        tm = re.match('##\\s*FINDING\\s*\\d*\\s*[—\\-:]\\s*(.*)', heading_line, re.IGNORECASE)
        f.title = tm.group(1).strip() if tm else ''
        f.repo_url = _normalize_repo_url(_field_a(block, 'Repository URL') or _field_a(block, 'Repository'))
        f.version = _field_a(block, 'Version Affected') or _field_a(block, 'Version')
        vt_raw = _field_a(block, 'Vulnerability Type')
        f.cwe = _extract_cwe(vt_raw)
        f.vuln_type = _normalize_vuln_type(vt_raw)
        f.severity = _field_a(block, 'Severity')
        f.expected_bounty = _parse_money(_field_a(block, 'Expected Bounty'))
        dm = re.search('\\*\\*\\s*Description\\s*:?\\s*\\*\\*\\s*:?', block, re.IGNORECASE)
        if dm:
            desc_content, _ = _extract_code_block(block, dm.end())
            f.description = desc_content.strip()
            pm = re.search('```[A-Za-z0-9_+\\-]+\\s*\\n', desc_content)
            if pm:
                poc_content, _ = _extract_code_block(desc_content, pm.start())
                f.poc_code = poc_content.strip()
        findings.append(f)
    return findings

def _parse_format_b(text: str) -> List[FindingSubmission]:
    """Parse the section-headed ``## TITLE / ## CWE / ...`` format."""
    f = FindingSubmission()
    f.title = _section_body(text, 'title')
    f.repo_url = _normalize_repo_url(_section_body(text, 'repository url') or _section_body(text, 'repository'))
    f.version = _section_body(text, 'version affected') or _section_body(text, 'version')
    cwe_body = _section_body(text, 'cwe')
    f.cwe = _extract_cwe(cwe_body)
    f.cvss_vector = _section_body(text, 'cvss vector') or _section_body(text, 'cvss')
    f.description = _section_body(text, 'description')
    f.severity = _section_body(text, 'severity')
    vt_raw = _section_body(text, 'vulnerability type') or cwe_body
    f.vuln_type = _normalize_vuln_type(vt_raw)
    f.expected_bounty = _parse_money(_section_body(text, 'expected bounty'))
    return [f]

def _parse_format_c(text: str) -> List[FindingSubmission]:
    """Parse the bold-inline-field ``## Target / ## Vulnerability Summary`` format."""
    f = FindingSubmission()
    f.title = _inline_bold(text, 'Title')
    f.repo_url = _normalize_repo_url(_inline_bold(text, 'Repository URL') or _inline_bold(text, 'Repository'))
    f.version = _inline_bold(text, 'Version Affected') or _inline_bold(text, 'Version')
    cwe_raw = _inline_bold(text, 'CWE')
    f.cwe = _extract_cwe(cwe_raw)
    f.cvss_vector = _inline_bold(text, 'CVSS Vector') or _inline_bold(text, 'CVSS')
    f.severity = _inline_bold(text, 'Severity')
    vt_raw = _inline_bold(text, 'Vulnerability Type') or cwe_raw
    f.vuln_type = _normalize_vuln_type(vt_raw)
    f.description = _section_body(text, 'description')
    f.expected_bounty = _parse_money(_inline_bold(text, 'Expected Bounty'))
    return [f]

def _parse_text(text: str) -> List[FindingSubmission]:
    """Auto-detect the markdown format and dispatch to the right parser."""
    if not text or not text.strip():
        return []
    if re.search('^##\\s*FINDING\\b', text, re.IGNORECASE | re.MULTILINE):
        return _parse_format_a(text)
    if re.search('\\*\\*\\s*(Repository|Title|Severity)\\s*\\*\\*', text, re.IGNORECASE):
        return _parse_format_c(text)
    return _parse_format_b(text)

def parse_submission_file(path: Union[str, Path], finding_n: Optional[int]=None) -> List[FindingSubmission]:
    """Parse a submission markdown file into :class:`FindingSubmission` records.

    *finding_n* (1-based) selects a single finding; out-of-range yields ``[]``.
    """
    path = Path(path)
    raw = path.read_text(encoding='utf-8')
    text = raw.replace('\r\n', '\n').replace('\r', '\n')
    findings = _parse_text(text)
    for f in findings:
        f.source_file = str(path)
    if finding_n is not None:
        idx = finding_n - 1
        if 0 <= idx < len(findings):
            return [findings[idx]]
        return []
    return findings

def scan_submission_queue(root: Union[str, Path]) -> List[FindingSubmission]:
    """Scan *root* for ``*_final_submission_ready.md`` files deterministically.

    Findings are de-duplicated by lowercased title (later files win) and
    returned sorted by ``expected_bounty`` descending.
    """
    root = Path(root)
    by_title: Dict[str, FindingSubmission] = {}
    for p in sorted(root.glob('*_final_submission_ready.md')):
        for f in parse_submission_file(p):
            by_title[f.title.strip().lower()] = f
    results = list(by_title.values())
    results.sort(key=lambda f: f.expected_bounty, reverse=True)
    return results