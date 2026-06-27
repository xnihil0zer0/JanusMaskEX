"""RED oracle for ngv2.pathtrav_detect -- the deterministic CWE-22 (Path
Traversal) recon scanner.

A PURE filesystem tool (analog of ngv2.deser_detect): walks a repo, scans
``*.py`` for path/archive sinks (extractall/tarfile/zipfile/send_file as
intrinsic sinks; open/os.path.join as tainted sinks needing a traversal
marker), and returns a fixed-shape dict whose ``findings`` use the SAME keys
``ngv2.pattern_scanner`` emits so they integrate with the scan catalog and
``ngv2.confidence_signals``. No network, clock, randomness, or subprocess --
fully deterministic and stdlib-only. Repos are materialised under ``tmp_path``.

Grounded in the real corpus (zilliztech-gptcache): ``open(img_path)`` and
``open(f_path, "wb")`` (dynamic, flagged); ``open("/path/to/merlion.png")``
(literal, not flagged); the canonical ML Zip/Tar-Slip ``.extractall`` sink.
"""
import os

from ngv2.pathtrav_detect import (
    detect_path_traversal,
    PATHTRAV_RULES,
    SKIP_DIRS,
    is_excluded_path,
)

FINDING_KEYS = {'id', 'file', 'line', 'code', 'severity', 'cwe', 'owasp', 'description'}
RESULT_KEYS = {'repo_path', 'files_checked', 'has_path_traversal', 'risk_level',
               'total_findings', 'findings'}


def _write(root, relpath, text):
    p = os.path.join(root, relpath)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(text)
    return p


# --- rules-as-data contract -------------------------------------------------
def test_rules_shape_is_cwe_22_catalog():
    assert isinstance(PATHTRAV_RULES, dict) and PATHTRAV_RULES
    for rid, meta in PATHTRAV_RULES.items():
        assert isinstance(rid, str) and rid
        assert {'pattern', 'taint', 'severity', 'cwe', 'owasp', 'description'} <= set(meta)
        assert meta['cwe'] == 'CWE-22'
        assert isinstance(meta['taint'], bool)
    joined = ' '.join(m['pattern'] for m in PATHTRAV_RULES.values())
    # the canonical archive-extraction (Zip/Tar Slip) sink must be present
    assert 'extractall' in joined
    # both an intrinsic (taint False) and a tainted (taint True) rule exist
    taints = {m['taint'] for m in PATHTRAV_RULES.values()}
    assert taints == {True, False}


def test_skip_dirs_contract():
    assert isinstance(SKIP_DIRS, set)
    assert {'.git', 'node_modules', '__pycache__', '.venv', 'site-packages'} <= SKIP_DIRS


# --- intrinsic sink detection (no taint marker required) --------------------
def test_detects_extractall_zip_slip_and_finding_shape(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'pkg/loader.py',
           'import tarfile\n'
           'def unpack(archive, dest):\n'
           '    tf = tarfile.open(archive)\n'
           '    tf.extractall(dest)\n')

    res = detect_path_traversal(repo)
    assert set(res.keys()) == RESULT_KEYS
    assert res['has_path_traversal'] is True
    ids = {f['id'] for f in res['findings']}
    assert 'pathtrav_extractall' in ids
    assert 'pathtrav_tarfile' in ids
    extract = next(f for f in res['findings'] if f['id'] == 'pathtrav_extractall')
    assert set(extract.keys()) == FINDING_KEYS
    assert extract['cwe'] == 'CWE-22'
    assert extract['severity'] == 'critical'


def test_detects_zipfile_and_send_file(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'z.py', 'import zipfile\nzf = zipfile.ZipFile(path)\n')
    _write(repo, 's.py', 'from flask import send_file\nreturn send_file(user_path)\n')
    res = detect_path_traversal(repo)
    ids = {f['id'] for f in res['findings']}
    assert 'pathtrav_zipfile' in ids
    assert 'pathtrav_send_file' in ids


# --- tainted sink detection (open / os.path.join) ---------------------------
def test_detects_dynamic_open_with_taint_marker(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'r.py',
           'def load(filename):\n'
           '    with open(filename, "rb") as f:\n'
           '        return f.read()\n')
    res = detect_path_traversal(repo)
    ids = {f['id'] for f in res['findings']}
    assert 'pathtrav_open' in ids


def test_detects_os_path_join_with_user_component(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'j.py',
           'import os\n'
           'full = os.path.join(base_dir, request_filename)\n')
    res = detect_path_traversal(repo)
    ids = {f['id'] for f in res['findings']}
    assert 'pathtrav_join' in ids


# --- false-positive exclusion (the sink_quality analog) ---------------------
def test_literal_open_is_not_flagged(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'const.py',
           'with open("README.md", "r") as fh:\n'
           '    text = fh.read()\n')
    res = detect_path_traversal(repo)
    assert res['has_path_traversal'] is False
    assert res['findings'] == []


def test_secure_filename_sanitized_open_not_flagged(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'safe.py',
           'from werkzeug.utils import secure_filename\n'
           'p = open(secure_filename(filename), "rb")\n')
    res = detect_path_traversal(repo)
    assert res['has_path_traversal'] is False
    assert res['findings'] == []


def test_comment_and_excluded_paths_ignored(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'doc.py',
           '# open(user_path) -- only a comment\n'
           'x = 1\n')
    _write(repo, 'tests/test_io.py', 'open(filename, "rb")\n')
    _write(repo, 'docs/demo.py', 'tarfile.open(archive).extractall(dest)\n')
    _write(repo, 'setup.py', 'with open(file_name) as f:\n    pass\n')
    res = detect_path_traversal(repo)
    assert res['has_path_traversal'] is False
    assert res['findings'] == []
    assert is_excluded_path('tests/test_io.py') is True
    assert is_excluded_path('gptcache/utils/response.py') is False


def test_skip_dirs_pruned(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'app.py', 'x = 1\n')
    _write(repo, 'node_modules/evil.py', 'open(filename, "rb")\n')
    res = detect_path_traversal(repo)
    assert res['files_checked'] == 1
    assert res['has_path_traversal'] is False


def test_non_py_and_clean_repo_negative(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'notes.txt', 'open(filename)\n')
    _write(repo, 'clean.py', 'import json\nd = json.loads(text)\n')
    res = detect_path_traversal(repo)
    assert res['has_path_traversal'] is False
    assert res['files_checked'] == 1  # only clean.py


# --- risk / error / purity --------------------------------------------------
def test_non_directory_error_shape(tmp_path):
    missing = str(tmp_path / 'nope')
    res = detect_path_traversal(missing)
    assert res['error'] == f'Not a directory: {missing}'
    assert res['has_path_traversal'] is False
    assert res['findings'] == []


def test_pure_and_deterministic(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'a.py', 'import tarfile\ntarfile.open(p).extractall(d)\n')
    assert detect_path_traversal(repo) == detect_path_traversal(repo)
