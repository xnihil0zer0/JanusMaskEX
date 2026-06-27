"""RED oracle for ngv2.ssrf_detect -- the deterministic CWE-918 (Server-Side
Request Forgery) recon scanner.

A PURE filesystem tool (analog of ngv2.deser_detect): walks a repo, scans
``*.py`` for HTTP-client sinks with a non-constant URL (requests/urllib/httpx),
and returns a fixed-shape dict whose ``findings`` use the SAME keys
``ngv2.pattern_scanner`` emits so they integrate with the scan catalog and
``ngv2.confidence_signals``. No network, clock, randomness, or subprocess --
fully deterministic and stdlib-only. The oracle materialises repos under
``tmp_path``; nothing touches the real filesystem outside it.

The real corpus examples this oracle is grounded in (zilliztech-gptcache):
``requests.get(dep.data)`` (data_manager.py), ``requests.get(url)``
(utils/response.py), and the literal/excluded false positives below.
"""
import os

from ngv2.ssrf_detect import (
    detect_ssrf,
    SSRF_RULES,
    SKIP_DIRS,
    is_excluded_path,
)

# Finding keys must match ngv2.pattern_scanner's finding shape exactly so the
# findings flow through confidence_signals / the scan catalog unchanged.
FINDING_KEYS = {'id', 'file', 'line', 'code', 'severity', 'cwe', 'owasp', 'description'}
RESULT_KEYS = {'repo_path', 'files_checked', 'has_ssrf', 'risk_level',
               'total_findings', 'findings'}


def _write(root, relpath, text):
    p = os.path.join(root, relpath)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(text)
    return p


# --- rules-as-data contract -------------------------------------------------
def test_rules_shape_is_cwe_918_catalog():
    assert isinstance(SSRF_RULES, dict) and SSRF_RULES
    for rid, meta in SSRF_RULES.items():
        assert isinstance(rid, str) and rid
        assert {'pattern', 'severity', 'cwe', 'owasp', 'description'} <= set(meta)
        assert meta['cwe'] == 'CWE-918'
        assert isinstance(meta['pattern'], str) and meta['pattern']
    # the three corpus-relevant client families must be represented
    joined = ' '.join(m['pattern'] for m in SSRF_RULES.values())
    assert 'requests' in joined
    assert 'urlopen' in joined or 'urllib' in joined
    assert 'httpx' in joined


def test_skip_dirs_contract():
    assert isinstance(SKIP_DIRS, set)
    assert {'.git', 'node_modules', '__pycache__', '.venv', 'site-packages'} <= SKIP_DIRS


# --- positive detection (researched patterns) -------------------------------
def test_detects_requests_dynamic_url_and_finding_shape(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'pkg/response.py',
           'import requests\n'
           'def fetch(url):\n'
           '    return requests.get(url).content\n')

    res = detect_ssrf(repo)

    assert set(res.keys()) == RESULT_KEYS
    assert res['repo_path'] == repo
    assert res['has_ssrf'] is True
    assert res['total_findings'] == len(res['findings']) >= 1
    f = res['findings'][0]
    assert set(f.keys()) == FINDING_KEYS
    assert f['id'] == 'ssrf_requests'
    assert f['cwe'] == 'CWE-918'
    assert f['file'] == os.path.join('pkg', 'response.py')
    assert f['line'] == 3
    assert 'requests.get' in f['code']


def test_detects_urllib_and_httpx_dynamic(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'a.py',
           'from urllib.request import urlopen\n'
           'r = urlopen(target_url)\n')
    _write(repo, 'b.py',
           'import httpx\n'
           'resp = httpx.get(user_endpoint)\n')

    res = detect_ssrf(repo)
    ids = {f['id'] for f in res['findings']}
    assert 'ssrf_urllib' in ids
    assert 'ssrf_httpx' in ids


def test_detects_fstring_and_concatenated_url(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'c.py',
           'import requests\n'
           'requests.get(f"https://{host}/api")\n'
           'requests.post("https://api/" + path)\n')
    res = detect_ssrf(repo)
    assert res['total_findings'] == 2


# --- false-positive exclusion (the sink_quality analog) ---------------------
def test_hardcoded_literal_url_is_not_flagged(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'const.py',
           'import requests\n'
           'PING = requests.get("https://fixed.example.com/health")\n')
    res = detect_ssrf(repo)
    assert res['has_ssrf'] is False
    assert res['findings'] == []


def test_comment_and_docstring_lines_ignored(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'doc.py',
           '# requests.get(url) -- only a comment\n'
           '    # httpx.get(url) indented comment\n'
           'x = 1\n')
    res = detect_ssrf(repo)
    assert res['has_ssrf'] is False
    assert res['findings'] == []


def test_excluded_paths_are_skipped(tmp_path):
    repo = str(tmp_path)
    # a real, dynamic sink but in vendored/test/docs/example trees -> excluded
    _write(repo, 'tests/test_net.py', 'import requests\nrequests.get(url)\n')
    _write(repo, 'docs/demo.py', 'import requests\nrequests.get(url)\n')
    _write(repo, 'vendor/lib.py', 'import requests\nrequests.get(url)\n')
    _write(repo, 'setup.py', 'import requests\nrequests.get(url)\n')
    res = detect_ssrf(repo)
    assert res['has_ssrf'] is False
    assert res['findings'] == []
    assert is_excluded_path('tests/test_net.py') is True
    assert is_excluded_path('docs/demo.py') is True
    assert is_excluded_path('gptcache/utils/response.py') is False


def test_skip_dirs_pruned(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'app.py', 'x = 1\n')
    _write(repo, 'node_modules/evil.py', 'import requests\nrequests.get(url)\n')
    _write(repo, '.venv/lib/pkg.py', 'import requests\nrequests.get(url)\n')
    res = detect_ssrf(repo)
    assert res['files_checked'] == 1
    assert res['has_ssrf'] is False


def test_non_py_and_clean_repo_negative(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'notes.txt', 'requests.get(url)\n')
    _write(repo, 'clean.py', 'import json\nd = json.loads(text)\n')
    res = detect_ssrf(repo)
    assert res['has_ssrf'] is False
    assert res['total_findings'] == 0
    assert res['files_checked'] == 1  # only clean.py


# --- risk levels / error / purity -------------------------------------------
def test_risk_level_scales(tmp_path):
    low = tmp_path / 'low'
    low.mkdir()
    _write(str(low), 'u.py', 'import requests\nrequests.get(url)\n')
    assert detect_ssrf(str(low))['risk_level'] == 'low'

    hi = tmp_path / 'hi'
    hi.mkdir()
    _write(str(hi), 'u.py',
           'requests.get(a)\nrequests.get(b)\nrequests.get(c)\n'
           'requests.get(d)\nrequests.get(e)\n')
    assert detect_ssrf(str(hi))['risk_level'] == 'high'


def test_non_directory_error_shape(tmp_path):
    missing = str(tmp_path / 'nope')
    res = detect_ssrf(missing)
    assert res['error'] == f'Not a directory: {missing}'
    assert res['has_ssrf'] is False
    assert res['findings'] == []


def test_pure_and_deterministic(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'a.py', 'import requests\nrequests.get(url)\n')
    assert detect_ssrf(repo) == detect_ssrf(repo)
