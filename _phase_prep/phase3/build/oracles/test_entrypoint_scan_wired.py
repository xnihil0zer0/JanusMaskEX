"""RED oracle for ngv2.entrypoint_scan -- Stage-1 public entry-point enumeration
that revives ngv2.web_framework_detect on a live path and implements the G6 MFF
model-load attacker boundary.

Hermetic: materialises repos under tmp_path; the framework detector can be
injected. One case proves the DEFAULT path actually calls the real revived
web_framework_detect (un-orphaning it).
"""
import os
import sys

from ngv2.entrypoint_scan import scan_entrypoints, load_entrypoint_sigs


def _write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(text)


def test_load_entrypoint_sigs_default_loads():
    sigs = load_entrypoint_sigs()
    assert isinstance(sigs, list) and sigs
    assert any(e['kind'] == 'model_load' for e in sigs)


def test_detects_fastapi_route_only_when_framework_present(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'app/api.py',
           'from fastapi import FastAPI\n'
           'app = FastAPI()\n'
           '@app.get("/x")\n'
           'def handler(): return 1\n')
    eps = scan_entrypoints(repo)  # default real detector sees fastapi import
    routes = [e for e in eps if e['kind'] == 'route']
    assert routes
    assert routes[0]['framework'] == 'fastapi'
    assert routes[0]['attacker_boundary'] == 'network'


def test_route_regex_suppressed_without_framework(tmp_path):
    # a decorator that looks like a route but no web framework imported/declared
    repo = str(tmp_path)
    _write(repo, 'thing.py', '@app.get("/x")\ndef h(): return 1\n')
    eps = scan_entrypoints(repo)
    assert [e for e in eps if e['kind'] == 'route'] == []


def test_g6_mff_model_load_is_attacker_boundary(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'loader.py',
           'import torch\n'
           'def load(p):\n'
           '    return torch.load(p)\n')
    eps = scan_entrypoints(repo)
    mff = [e for e in eps if e['kind'] == 'model_load']
    assert mff
    assert mff[0]['attacker_boundary'] == 'model_file'


def test_argparse_cli_entrypoint(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'cli.py',
           'import argparse\n'
           'p = argparse.ArgumentParser()\n')
    eps = scan_entrypoints(repo)
    assert any(e['kind'] == 'cli' and e['framework'] == 'argparse' for e in eps)


def test_excluded_paths_and_nondir(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'tests/test_x.py', 'import torch\ntorch.load(p)\n')
    _write(repo, 'docs/demo.py', 'import torch\ntorch.load(p)\n')
    assert scan_entrypoints(repo) == []
    assert scan_entrypoints(str(tmp_path / 'nope')) == []


def test_default_path_uses_real_web_framework_detect(tmp_path):
    # invoking scan_entrypoints with the default detector must load the revived
    # module into sys.modules (live-path / anti-orphan proof)
    repo = str(tmp_path)
    _write(repo, 'app/api.py',
           'import flask\n'
           'app = flask.Flask(__name__)\n'
           '@app.route("/p")\n'
           'def h(): return 1\n')
    scan_entrypoints(repo)
    assert 'ngv2.web_framework_detect' in sys.modules


def test_injected_detector_is_honored(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'srv.py', '@app.get("/x")\ndef h(): return 1\n')
    fake = lambda path: {'frameworks': [{'name': 'fastapi'}]}
    eps = scan_entrypoints(repo, detect_frameworks=fake)
    assert any(e['kind'] == 'route' and e['framework'] == 'fastapi' for e in eps)
