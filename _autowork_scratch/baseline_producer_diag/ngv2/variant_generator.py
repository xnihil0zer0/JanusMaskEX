"""Deterministic adversarial evasion-variant generator for NobleGreedv2.

Given a detection rule (a plain ``dict``) and a target CWE, this module
produces inert code *variants* that achieve the same dangerous operation via
alternative APIs, idiom transforms, or a multi-file source/sink split.

The module is PURE and DETERMINISTIC: no ``random``, no clock, no network.
Variant selection is keyed off the caller-supplied integer index, and the
strategy tables are static literals, so identical inputs always yield
byte-identical output. JanusMask never executes the generated code; the
variants are text payloads used downstream to probe rule robustness.

Standard library only -- no third-party imports, and no cross-imports of the
sibling ``ngv2`` modules.
"""
from __future__ import annotations
import json
from typing import Any, Dict, List
__all__ = ['EVASION_STRATEGIES', 'VARIANT_FIELDS', 'get_strategies_for_cwe', 'generate_api_variant', 'generate_idiom_variant', 'generate_multifile_variant', 'generate_variants']
VARIANT_FIELDS = ('variant_id', 'target_rule', 'cwe', 'evasion_strategy', 'code', 'description', 'expected_detection')
EVASION_STRATEGIES: Dict[str, Dict[str, Any]] = {'CWE-502': {'api_alternatives': [{'original': 'pickle.loads', 'alternative': '_pickle.loads', 'code': 'import _pickle\n_pickle.loads(data)\n'}, {'original': 'pickle.loads', 'alternative': 'pickle.Unpickler.load', 'code': 'import io, pickle\npickle.Unpickler(io.BytesIO(data)).load()\n'}], 'idiom_transforms': [{'name': 'module_alias', 'code': 'import pickle as _p\n_p.loads(data)\n'}, {'name': 'attr_indirection', 'code': "import pickle\nfn = getattr(pickle, 'loads')\nfn(data)\n"}], 'multi_file': {'source_file': {'name': 'payload_source.py', 'code': 'def get_blob():\n    return _network_blob\n'}, 'sink_file': {'name': 'payload_sink.py', 'code': 'import pickle\nfrom payload_source import get_blob\npickle.loads(get_blob())\n'}}}, 'CWE-78': {'api_alternatives': [{'original': 'os.system', 'alternative': 'subprocess.call', 'code': 'import subprocess\nsubprocess.call(cmd, shell=True)\n'}, {'original': 'os.system', 'alternative': 'os.popen', 'code': 'import os\nos.popen(cmd).read()\n'}], 'idiom_transforms': [{'name': 'callable_indirection', 'code': 'import os\nrun = os.system\nrun(cmd)\n'}, {'name': 'shell_wrapper', 'code': "import subprocess\nsubprocess.Popen(['/bin/sh', '-c', cmd])\n"}], 'multi_file': {'source_file': {'name': 'cmd_source.py', 'code': 'def build_cmd():\n    return _user_cmd\n'}, 'sink_file': {'name': 'cmd_sink.py', 'code': 'import os\nfrom cmd_source import build_cmd\nos.system(build_cmd())\n'}}}, 'CWE-22': {'api_alternatives': [{'original': 'open', 'alternative': 'io.open', 'code': 'import io\nio.open(path).read()\n'}, {'original': 'open', 'alternative': 'pathlib.Path.read_text', 'code': 'import pathlib\npathlib.Path(path).read_text()\n'}], 'idiom_transforms': [{'name': 'join_indirection', 'code': 'import os\nfull = os.path.join(base, user_part)\nopen(full).read()\n'}, {'name': 'builtin_alias', 'code': '_open = open\n_open(path).read()\n'}], 'multi_file': {'source_file': {'name': 'path_source.py', 'code': 'def build_path():\n    return _user_path\n'}, 'sink_file': {'name': 'path_sink.py', 'code': 'from path_source import build_path\nopen(build_path()).read()\n'}}}, 'CWE-89': {'api_alternatives': [{'original': 'cursor.execute', 'alternative': 'cursor.executescript', 'code': 'cursor.executescript(query)\n'}, {'original': 'cursor.execute', 'alternative': 'connection.execute', 'code': 'connection.execute(query)\n'}], 'idiom_transforms': [{'name': 'format_concat', 'code': "cursor.execute('SELECT * FROM t WHERE id = ' + str(uid))\n"}, {'name': 'percent_format', 'code': "cursor.execute('SELECT * FROM t WHERE id = %s' % uid)\n"}], 'multi_file': {'source_file': {'name': 'query_source.py', 'code': "def build_query():\n    return 'SELECT * FROM t WHERE id = ' + _user_id\n"}, 'sink_file': {'name': 'query_sink.py', 'code': 'from query_source import build_query\ncursor.execute(build_query())\n'}}}, 'CWE-79': {'api_alternatives': [{'original': 'flask.render_template_string', 'alternative': 'jinja2.Template.render', 'code': 'import jinja2\njinja2.Template(tpl).render()\n'}, {'original': 'html_escape', 'alternative': 'mark_safe', 'code': 'rendered = mark_safe(user_input)\n'}], 'idiom_transforms': [{'name': 'string_concat', 'code': "page = '<div>' + user_input + '</div>'\n"}, {'name': 'format_inject', 'code': "page = '<div>{}</div>'.format(user_input)\n"}], 'multi_file': {'source_file': {'name': 'html_source.py', 'code': "def build_fragment():\n    return '<div>' + _user_input + '</div>'\n"}, 'sink_file': {'name': 'html_sink.py', 'code': 'from html_source import build_fragment\nresponse.write(build_fragment())\n'}}}}
_FALLBACK_CWE = 'CWE-502'

def get_strategies_for_cwe(cwe: str) -> Dict[str, Any]:
    """Return the strategy block for ``cwe``, falling back to CWE-502.

    The returned object is the live strategy dict (identity-preserving), not a
    copy, so callers reference the canonical table.
    """
    return EVASION_STRATEGIES.get(cwe, EVASION_STRATEGIES[_FALLBACK_CWE])

def generate_api_variant(rule: Dict[str, Any], alt: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Build an API-substitution variant from a single alternative entry."""
    return {'variant_id': 'VAR-{}'.format(index), 'target_rule': rule['id'], 'cwe': rule['cwe'], 'evasion_strategy': 'api_substitution', 'code': alt['code'], 'description': 'Replace {} with {}'.format(alt['original'], alt['alternative']), 'expected_detection': False}

def generate_idiom_variant(rule: Dict[str, Any], transform: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Build an idiom-transformation variant from a single transform entry."""
    return {'variant_id': 'VAR-{}'.format(index), 'target_rule': rule['id'], 'cwe': rule['cwe'], 'evasion_strategy': 'idiom_transformation', 'code': transform['code'], 'description': 'Idiom transform: {}'.format(transform['name']), 'expected_detection': False}

def generate_multifile_variant(rule: Dict[str, Any], target_cwe: str, index: int) -> Dict[str, Any]:
    """Build a multi-file source/sink split variant.

    The strategy block is looked up by ``target_cwe`` (with deterministic
    fallback), while the reported ``cwe`` is taken from the rule.  ``code`` is a
    JSON-encoded ``{"source": ..., "sink": ...}`` bundle.
    """
    mf = get_strategies_for_cwe(target_cwe)['multi_file']
    source = mf['source_file']
    sink = mf['sink_file']
    return {'variant_id': 'VAR-{}'.format(index), 'target_rule': rule['id'], 'cwe': rule['cwe'], 'evasion_strategy': 'multi_file', 'code': json.dumps({'source': source, 'sink': sink}), 'description': 'Multi-file: source in {}, sink in {}'.format(source['name'], sink['name']), 'expected_detection': False, 'files': [source, sink]}

def generate_variants(rule: Dict[str, Any], target_cwe: str) -> List[Dict[str, Any]]:
    """Generate the deterministic, de-duplicated variant sequence for a rule.

    Selection is fixed: the first API alternative, the first idiom transform,
    and the multi-file split for ``target_cwe`` (with CWE-502 fallback).  The
    returned list is ordered VAR-1 (api), VAR-2 (idiom), VAR-3 (multi_file).
    The input ``rule`` is never mutated.
    """
    strategies = get_strategies_for_cwe(target_cwe)
    variants: List[Dict[str, Any]] = []
    seen_codes = set()
    ordered = [generate_api_variant(rule, strategies['api_alternatives'][0], 1), generate_idiom_variant(rule, strategies['idiom_transforms'][0], 2), generate_multifile_variant(rule, target_cwe, 3)]
    for variant in ordered:
        dedup_token = (variant['evasion_strategy'], variant['code'])
        if dedup_token in seen_codes:
            continue
        seen_codes.add(dedup_token)
        variants.append(variant)
    return variants