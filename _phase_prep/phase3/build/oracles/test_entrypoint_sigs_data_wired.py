"""RED oracle for the Stage-1 rules-as-data catalog
data/ngv2/reachability_rules/entrypoint_sigs.json.

Pure JSON schema + coverage: web/CLI frameworks present, every signature compiles,
and -- folding Gap G6 -- a model_load entry-point boundary (attacker = the model
FILE) is present so MFF loaders are treated as attacker boundaries.
"""
import json
import os
import re

import ngv2

_RULES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(ngv2.__file__))),
    'data', 'ngv2', 'reachability_rules')


def _load(name):
    with open(os.path.join(_RULES_DIR, name), 'r', encoding='utf-8') as f:
        return json.load(f)


def test_entrypoint_sigs_schema_and_framework_coverage():
    entries = _load('entrypoint_sigs.json')['entrypoints']
    assert isinstance(entries, list) and entries
    frameworks = {e['framework'] for e in entries}
    assert {'fastapi', 'flask', 'django', 'click', 'argparse'} <= frameworks
    kinds = {e['kind'] for e in entries}
    assert {'route', 'cli', 'model_load'} <= kinds


def test_each_signature_regex_compiles():
    entries = _load('entrypoint_sigs.json')['entrypoints']
    for e in entries:
        assert {'framework', 'kind', 'attacker_boundary', 'signature_regex'} <= set(e)
        assert isinstance(e['signature_regex'], list) and e['signature_regex']
        for pat in e['signature_regex']:
            re.compile(pat)  # edge: every signature must be a valid regex


def test_g6_mff_model_load_boundary_present():
    entries = _load('entrypoint_sigs.json')['entrypoints']
    mff = [e for e in entries
           if e['kind'] == 'model_load' and e['attacker_boundary'] == 'model_file']
    assert mff, 'G6 MFF model-load entry-point boundary missing'
    joined = ' '.join(p for e in mff for p in e['signature_regex'])
    assert 'torch' in joined and 'pickle' in joined  # edge: MFF loaders named
