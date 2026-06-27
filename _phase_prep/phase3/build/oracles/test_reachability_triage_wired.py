"""RED oracle for ngv2.reachability_triage -- Stage-3 LLM scope/auth triage.

Pure prompt builder + judge over an injected complete seam (no network). Each
verdict maps to the right band; malformed/erroring output fail-safes to MANUAL,
never a silent DROP.
"""
from ngv2.reachability_triage import (
    build_triage_prompt,
    judge,
    classify_to_band,
    CLASSIFICATIONS,
)

_FINDING = {'cwe': 'CWE-502', 'file': 'app/runner.py', 'line': 88}
_PATH = ['app/server.py:12 — request body', 'app/runner.py:88 — pickle.loads']


def test_prompt_contains_source_sink_path_and_json_instruction():
    prompt = build_triage_prompt(_FINDING, _PATH, ['def runner(body): pickle.loads(body)'])
    assert 'CWE-502' in prompt
    assert 'app/server.py:12' in prompt   # source
    assert 'app/runner.py:88' in prompt   # sink
    assert 'pickle.loads' in prompt
    assert 'classification' in prompt and 'JSON' in prompt
    for c in CLASSIFICATIONS:
        assert c in prompt


def test_prompt_is_deterministic():
    assert build_triage_prompt(_FINDING, _PATH) == build_triage_prompt(_FINDING, _PATH)


def _seam(text):
    def complete(messages, **kwargs):
        return text
    return complete


def test_reachable_unauth_maps_to_admit():
    res = judge(_FINDING, _PATH, complete=_seam(
        '{"classification": "reachable_unauth", "justification": "public POST route"}'))
    assert res['band'] == 'ADMIT'
    assert res['classification'] == 'reachable_unauth'


def test_internal_only_and_out_of_scope_map_to_drop():
    assert judge(_FINDING, _PATH, complete=_seam(
        '{"classification": "internal_only", "justification": "hardcoded"}'))['band'] == 'DROP'
    assert judge(_FINDING, _PATH, complete=_seam(
        '{"classification": "out_of_scope", "justification": "dev tool"}'))['band'] == 'DROP'


def test_auth_gated_maps_to_manual():
    assert judge(_FINDING, _PATH, complete=_seam(
        '{"classification": "auth_gated", "justification": "admin only"}'))['band'] == 'MANUAL'


def test_malformed_output_failsafe_manual_never_silent_drop():
    assert judge(_FINDING, _PATH, complete=_seam('not json at all'))['band'] == 'MANUAL'
    assert judge(_FINDING, _PATH, complete=_seam('{"foo": "bar"}'))['band'] == 'MANUAL'


def test_llm_error_failsafe_manual():
    def boom(messages, **kwargs):
        raise RuntimeError('model down')
    assert judge(_FINDING, _PATH, complete=boom)['band'] == 'MANUAL'


def test_classify_to_band_unknown_is_manual():
    assert classify_to_band('weird') == 'MANUAL'
    assert classify_to_band(None) == 'MANUAL'
    assert classify_to_band('reachable_unauth') == 'ADMIT'
