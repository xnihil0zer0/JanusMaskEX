"""Oracle (gap A): template selection keyed off the TRUE sink semantics.

The pipeline reaches detonation but PoCs fail-close at ``detonation_evidence``
(detonated=True, reproduced=False). A confirmed root cause: a dbgpt finding was
DECLARED ``category=CWE-22`` (path traversal) but its real
``sink_name=asyncio.create_subprocess_exec`` is a command-exec / CWE-78 sink.
``poc_writer`` chose the template from the *declared* CWE, so it applied a
path-traversal template to a subprocess sink -- guaranteeing a non-reproducing
PoC.

This oracle pins the fix: ``_resolve_template`` must derive the CWE from the
finding's concrete ``sink_name`` / ``call_sites`` and let that OVERRIDE a
conflicting declared ``category`` (the declared category is often a mis-triage),
while still falling back to the declared category when there is no sink hint or
the sink is ambiguous.

Findings carry accurate ``sink_name`` / ``call_sites`` as attributes (copied by
``_coerce_finding``); the live worker threads the same fields through the dict
finding. The oracle exercises both the ``Finding`` shape and the plain-dict
shape the live poc worker reads from ``context['prior_findings']``.

RED on HEAD:
  * the dbgpt case resolves to CWE-22 (declared) instead of CWE-78 (sink truth);
  * the sink-only ``eval`` case raises KeyError (no category to fall back to).
GREEN after the gap-A edit + the payloads agent (B) providing the CWE-78 and
CWE-94 restricted-code-injection templates (which already exist on HEAD as
``_py_command_injection`` / ``_py_code_injection``).
"""
from ngv2.contracts import Finding
from ngv2.poc_writer import _resolve_template, _coerce_finding, sink_to_cwe


def _finding(category="", sink_name="", call_sites=None, **kw):
    f = Finding(
        id=kw.get("id", "F"), target=kw.get("target", "x"),
        category=category, severity="high",
        title=kw.get("title", "t"), description=kw.get("description", "d"),
        evidence=kw.get("evidence", ["x.py:2"]),
    )
    setattr(f, "sink_name", sink_name)
    setattr(f, "call_sites", list(call_sites or []))
    return f


# --- the concrete sink -> CWE classifier ---------------------------------

def test_sink_to_cwe_command_exec_family():
    assert sink_to_cwe("asyncio.create_subprocess_exec", []) == "CWE-78"
    assert sink_to_cwe("subprocess.Popen", []) == "CWE-78"
    assert sink_to_cwe("os.system", []) == "CWE-78"
    assert sink_to_cwe("os.popen", []) == "CWE-78"
    assert sink_to_cwe("", ["await asyncio.create_subprocess_shell(cmd)"]) == "CWE-78"


def test_sink_to_cwe_code_injection_family():
    assert sink_to_cwe("eval", []) == "CWE-94"
    assert sink_to_cwe("exec", []) == "CWE-94"
    assert sink_to_cwe("compile", []) == "CWE-94"
    assert sink_to_cwe("", ["eval(snippet)"]) == "CWE-94"


def test_sink_to_cwe_other_families():
    assert sink_to_cwe("cursor.execute", []) == "CWE-89"
    assert sink_to_cwe("pickle.loads", []) == "CWE-502"
    assert sink_to_cwe("requests.get", []) == "CWE-918"
    assert sink_to_cwe("send_file", []) == "CWE-22"


def test_sink_to_cwe_ambiguous_or_empty_returns_none():
    # no sink hint at all -> no override
    assert sink_to_cwe("", []) is None
    # an idiom that doesn't match any sink family -> no override
    assert sink_to_cwe("some_unknown_helper", ["frobnicate(x)"]) is None


# --- the OVERRIDE precedence in _resolve_template -------------------------

def test_sink_overrides_mistriaged_category():
    """The dbgpt root case: declared CWE-22 but the sink is a subprocess exec."""
    f = _finding(
        category="CWE-22",
        sink_name="asyncio.create_subprocess_exec",
        call_sites=["await asyncio.create_subprocess_exec(*cmd)"],
    )
    assert _resolve_template(f).cwe == "CWE-78"


def test_eval_sink_resolves_code_injection_without_category():
    """A finding with no declared category but an eval sink resolves to CWE-94."""
    f = _finding(category="", sink_name="eval", call_sites=["eval(snippet)"])
    assert _resolve_template(f).cwe == "CWE-94"


def test_eval_two_step_call_site_resolves_code_injection():
    """sink_name empty but the call-site idiom names eval -> CWE-94."""
    f = _finding(category="", sink_name="", call_sites=["return eval(user_input)"])
    assert _resolve_template(f).cwe == "CWE-94"


def test_no_sink_hint_falls_back_to_declared_category():
    """When there's no sink hint, the declared category is preserved."""
    f = _finding(category="CWE-22", sink_name="", call_sites=[])
    assert _resolve_template(f).cwe == "CWE-22"


def test_ambiguous_sink_falls_back_to_declared_category():
    """A sink that maps to no family must not clobber the declared category."""
    f = _finding(category="CWE-89", sink_name="helper", call_sites=["helper(q)"])
    assert _resolve_template(f).cwe == "CWE-89"


def test_sink_agreeing_with_category_is_stable():
    f = _finding(category="CWE-78", sink_name="subprocess.run", call_sites=[])
    assert _resolve_template(f).cwe == "CWE-78"


def test_dict_finding_shape_is_coerced_then_overridden():
    """The live poc worker reads plain-dict findings; the override must still
    apply after _coerce_finding copies sink_name/call_sites."""
    raw = {
        "id": "F", "target": "x", "category": "CWE-22", "severity": "high",
        "title": "t", "description": "d", "evidence": ["x.py:2"],
        "sink_name": "asyncio.create_subprocess_exec",
        "call_sites": ["await asyncio.create_subprocess_exec(*cmd)"],
    }
    coerced = _coerce_finding(raw)
    assert _resolve_template(coerced).cwe == "CWE-78"
