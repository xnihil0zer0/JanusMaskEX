"""RED oracle for ngv2.source_sink_prefilter -- the Stage-1 source x sink gate.

Keep a repo iff it has BOTH a public entry point AND a dangerous sink class.
Live-path (anti-orphan) assertions prove deser_detect AND web_framework_detect
are exercised on this module's path. Covers the G6 MFF mode (model-file boundary
+ deser sink -> keep even with no web route).
"""
import os
import sys

from ngv2.source_sink_prefilter import prefilter, collect_sinks


def _write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        f.write(text)


def test_keep_true_for_web_route_plus_pickle_sink(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'app/api.py',
           'from fastapi import FastAPI\n'
           'import pickle\n'
           'app = FastAPI()\n'
           '@app.post("/load")\n'
           'def load(body):\n'
           '    return pickle.loads(body)\n')
    res = prefilter(repo)
    assert res['keep'] is True
    assert res['mode'] == 'web'
    assert res['entrypoints'] and res['sinks']
    assert any(s['cwe'] == 'CWE-502' for s in res['sinks'])


def test_keep_false_route_but_no_sink(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'app/api.py',
           'from fastapi import FastAPI\n'
           'app = FastAPI()\n'
           '@app.get("/ping")\n'
           'def ping(): return "ok"\n')
    res = prefilter(repo)
    assert res['keep'] is False
    assert res['entrypoints']
    assert res['sinks'] == []


def test_keep_false_sink_but_no_entrypoint(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'lib/util.py',
           'import pickle\n'
           'def f(b): return pickle.loads(b)\n')
    # pickle.loads is a sink but is ALSO an MFF-irrelevant call; there is no
    # registered entrypoint regex for bare pickle.loads, only pickle.load.
    res = prefilter(repo)
    assert res['sinks']
    assert res['entrypoints'] == []
    assert res['keep'] is False


def test_g6_mff_mode_model_load_plus_deser(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'models/loader.py',
           'import torch\n'
           'def load_model(path):\n'
           '    return torch.load(path)\n')
    res = prefilter(repo)
    assert res['keep'] is True
    assert res['mode'] == 'mff'
    assert 'model_file' in res['boundaries']


def test_nondir_is_safe(tmp_path):
    res = prefilter(str(tmp_path / 'missing'))
    assert res['keep'] is False
    assert res['entrypoints'] == [] and res['sinks'] == []


def test_collect_sinks_excludes_bare_imports(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'm.py', 'import pickle\n')  # import only, no usage
    sinks = collect_sinks(repo)
    assert all(s['sink_class'] != 'deserialization' for s in sinks)


def test_live_path_revives_deser_and_web_framework_detect(tmp_path):
    repo = str(tmp_path)
    _write(repo, 'app/api.py',
           'from flask import Flask\n'
           'import pickle\n'
           'app = Flask(__name__)\n'
           '@app.route("/x")\n'
           'def x(): return pickle.loads(b"")\n')
    prefilter(repo)
    assert 'ngv2.deser_detect' in sys.modules
    assert 'ngv2.web_framework_detect' in sys.modules
