"""RED oracle for the Stage-1 rules-as-data catalog
data/ngv2/reachability_rules/sink_classes.json.

Pure JSON schema + coverage: every required CWE present, no duplicate ids, each
pattern compiles, every class names the bundled .ql specs it maps to.
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


def test_sink_classes_cover_required_cwes_no_dupes():
    classes = _load('sink_classes.json')['sink_classes']
    assert isinstance(classes, list) and classes
    ids = [c['id'] for c in classes]
    assert len(ids) == len(set(ids)), 'duplicate sink-class ids'
    cwes = {c['cwe'] for c in classes}
    assert {'CWE-22', 'CWE-78', 'CWE-94', 'CWE-502', 'CWE-918'} <= cwes


def test_sink_class_entries_are_well_formed():
    classes = _load('sink_classes.json')['sink_classes']
    for c in classes:
        assert {'id', 'cwe', 'lang', 'patterns', 'specs'} <= set(c)
        assert isinstance(c['patterns'], list) and c['patterns']
        assert isinstance(c['specs'], list) and c['specs']
        for pat in c['patterns']:
            re.compile(pat)  # edge: every pattern must be a valid regex


def test_deser_class_maps_to_bundled_502_specs():
    classes = _load('sink_classes.json')['sink_classes']
    deser = [c for c in classes if c['cwe'] == 'CWE-502']
    assert deser, 'CWE-502 deserialization sink class missing'
    specs = ' '.join(deser[0]['specs'])
    assert 'cwe502_pickle_load.ql' in specs and 'cwe502_torch_load.ql' in specs
