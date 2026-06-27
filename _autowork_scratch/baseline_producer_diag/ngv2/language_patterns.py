"""ngv2.language_patterns — deterministic, stdlib-only static vulnerability
pattern database.

This leaf is a pure lookup table. It maps a programming language to a list of
CWE-tagged regex patterns and exposes a ``run(args)`` shell that accepts an
argparse.Namespace-style object carrying a ``.language`` attribute.

There is no external tool, network, clock, randomness, filesystem access, or
code execution involved: every regex is a static string that compiles cleanly
via :func:`re.compile`, and lookups are deterministic dict accesses. Import and
every public call are side-effect-free and reproducible across runs/processes.
"""
from __future__ import annotations
from typing import Any
from typing import Dict
from typing import List
__all__ = ['PATTERNS', 'SUPPORTED_LANGUAGES', 'PATTERN_FIELDS', 'PATTERN_SEVERITIES', 'run']
PATTERN_FIELDS = ('name', 'regex', 'cwe', 'severity', 'description')
PATTERN_SEVERITIES = ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')

def _pattern(name: str, regex: str, cwe: str, severity: str, description: str) -> Dict[str, str]:
    """Build a single pattern record with the canonical field order."""
    values = (name, regex, cwe, severity, description)
    return dict(zip(PATTERN_FIELDS, values))
PATTERNS: Dict[str, List[Dict[str, str]]] = {'python': [_pattern('exec-eval', '\\b(?:eval|exec)\\s*\\(', 'CWE-95', 'CRITICAL', 'Dynamic code execution via eval/exec on untrusted input.'), _pattern('os-system', '\\bos\\.system\\s*\\(', 'CWE-78', 'CRITICAL', 'OS command execution through os.system.'), _pattern('subprocess-shell', '\\bsubprocess\\.\\w+\\([^)]*shell\\s*=\\s*True', 'CWE-78', 'HIGH', 'Subprocess invocation with shell=True enables injection.'), _pattern('pickle-loads', '\\bpickle\\.loads?\\s*\\(', 'CWE-502', 'HIGH', 'Deserialisation of untrusted data via pickle.'), _pattern('yaml-load', '\\byaml\\.load\\s*\\((?![^)]*Loader)', 'CWE-502', 'HIGH', 'yaml.load without a safe Loader deserialises arbitrary objects.'), _pattern('md5-usage', '\\bhashlib\\.md5\\s*\\(', 'CWE-327', 'MEDIUM', 'Use of the broken MD5 hashing algorithm.')], 'go': [_pattern('exec-command', '\\bexec\\.Command\\s*\\(', 'CWE-78', 'HIGH', 'Process execution via os/exec.Command.'), _pattern('sql-sprintf', 'fmt\\.Sprintf\\s*\\([^)]*(?:SELECT|INSERT|UPDATE|DELETE)', 'CWE-89', 'HIGH', 'SQL query assembled with fmt.Sprintf risks injection.'), _pattern('md5-new', '\\bmd5\\.New\\s*\\(', 'CWE-327', 'MEDIUM', 'Use of the broken MD5 hashing algorithm.'), _pattern('insecure-skip-verify', 'InsecureSkipVerify\\s*:\\s*true', 'CWE-295', 'HIGH', 'TLS certificate verification disabled.')], 'javascript': [_pattern('eval-call', '\\beval\\s*\\(', 'CWE-95', 'CRITICAL', 'Dynamic code execution via eval.'), _pattern('function-constructor', '\\bnew\\s+Function\\s*\\(', 'CWE-95', 'HIGH', 'Code construction via the Function constructor.'), _pattern('inner-html', '\\.innerHTML\\s*=', 'CWE-79', 'HIGH', 'Assignment to innerHTML can introduce DOM XSS.'), _pattern('child-process-exec', 'child_process\\.exec\\s*\\(', 'CWE-78', 'HIGH', 'Shell command execution via child_process.exec.'), _pattern('document-write', 'document\\.write\\s*\\(', 'CWE-79', 'MEDIUM', 'document.write with untrusted data enables XSS.')], 'java': [_pattern('runtime-exec', 'Runtime\\.getRuntime\\(\\)\\.exec\\s*\\(', 'CWE-78', 'CRITICAL', 'OS command execution via Runtime.exec.'), _pattern('sql-statement-concat', '(?:createStatement|Statement)\\s*\\([^)]*\\)[^;]*\\+', 'CWE-89', 'HIGH', 'SQL statement built with string concatenation.'), _pattern('object-input-stream', '\\bnew\\s+ObjectInputStream\\s*\\(', 'CWE-502', 'HIGH', 'Deserialisation of untrusted data via ObjectInputStream.'), _pattern('xml-external-entity', 'DocumentBuilderFactory\\.newInstance\\s*\\(', 'CWE-611', 'MEDIUM', 'XML parser construction may be vulnerable to XXE.')], 'php': [_pattern('eval-call', '\\beval\\s*\\(', 'CWE-95', 'CRITICAL', 'Dynamic code execution via eval.'), _pattern('shell-exec', '\\b(?:system|exec|passthru|shell_exec)\\s*\\(', 'CWE-78', 'CRITICAL', 'Shell command execution from PHP.'), _pattern('unserialize', '\\bunserialize\\s*\\(', 'CWE-502', 'HIGH', 'Deserialisation of untrusted data via unserialize.'), _pattern('include-variable', '\\b(?:include|require)(?:_once)?\\s*\\(\\s*\\$', 'CWE-98', 'HIGH', 'Dynamic file inclusion from a variable path.')], 'ruby': [_pattern('eval-call', '\\b(?:eval|instance_eval|class_eval)\\s*\\(', 'CWE-95', 'CRITICAL', 'Dynamic code execution via eval family.'), _pattern('backtick-exec', '(?:`[^`]*`|%x\\{)', 'CWE-78', 'HIGH', 'Shell command execution via backticks or %x.'), _pattern('yaml-load', 'YAML\\.load\\s*\\(', 'CWE-502', 'HIGH', 'YAML.load deserialises arbitrary Ruby objects.')], 'c': [_pattern('strcpy', '\\bstrcpy\\s*\\(', 'CWE-120', 'HIGH', 'Unbounded copy with strcpy risks buffer overflow.'), _pattern('gets', '\\bgets\\s*\\(', 'CWE-242', 'CRITICAL', 'Inherently unsafe gets() allows buffer overflow.'), _pattern('system-call', '\\bsystem\\s*\\(', 'CWE-78', 'HIGH', 'OS command execution via system().'), _pattern('sprintf', '\\bsprintf\\s*\\(', 'CWE-120', 'MEDIUM', 'sprintf into a fixed buffer can overflow.')]}
SUPPORTED_LANGUAGES: List[str] = sorted(PATTERNS.keys())

def run(args: Any) -> Dict[str, Any]:
    """Resolve the pattern set for ``args.language``.

    Returns an ``ok`` result carrying the matching pattern list, or an
    ``error`` result listing the supported languages.  The call never mutates
    the underlying :data:`PATTERNS` table.
    """
    language = _normalize(getattr(args, 'language', None))
    if language in PATTERNS:
        patterns = PATTERNS[language]
        return {'status': 'ok', 'language': language, 'patterns': patterns, 'pattern_count': len(patterns)}
    return {'status': 'error', 'language': language, 'error': 'unsupported language: {0!r}'.format(language), 'supported': SUPPORTED_LANGUAGES}

def _normalize(language: Any) -> str:
    """Lowercase and strip a language identifier; tolerate non-strings."""
    if language is None:
        return ''
    return str(language).strip().lower()
'ngv2.language_patterns -- deterministic, stdlib-only static\nvulnerability-pattern database.\n\nThis leaf is a pure lookup table: it maps a programming language to a list of\nCWE-tagged regex patterns and exposes a ``run(args)`` entry point that accepts\nan ``argparse.Namespace``-style object with a ``.language`` attribute.\n\nThere is no external tool, network access, clock, randomness, or code\nexecution here.  Every regex is a static string that compiles under ``re``,\nand the lookup is a deterministic dict access, so identical inputs always\nproduce identical output.\n'