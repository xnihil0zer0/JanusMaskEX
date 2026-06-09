"""RED oracle — authoritative contract for autocompiler/vacuity.py (leaf ac-vacuity).

Contract: three pure AST gates, each returning a GateResult-shaped object
(attrs ``ok`` bool, ``reason`` str), all fail-closed (unparseable source =>
ok=False) and never raising:

* ``check_vacuity_stub(src)`` — ok=False when EVERY function/method body in
  ``src`` is a stub (only ``pass`` / ``...`` / ``raise NotImplementedError`` /
  a lone constant or docstring); ok=True when at least one function does real
  work. A module with zero functions but real top-level statements is ok=True.
* ``check_complexity_floor(src, min_by_type)`` — ``min_by_type`` maps AST node
  type name (e.g. 'FunctionDef') to the MINIMUM number of body statements each
  such node must contain (docstring not counted); any node below floor =>
  ok=False.
* ``check_no_exception_swallow(src)`` — an except handler whose body is only
  ``pass``/``...`` (a swallow) => ok=False; handlers that re-raise, log, or
  otherwise act are ok=True.
"""
from autocompiler.vacuity import (check_vacuity_stub, check_complexity_floor,
                                  check_no_exception_swallow)

REAL = 'def add(a, b):\n    total = a + b\n    return total\n'


def test_all_stub_module_rejected():
    src = 'def f():\n    pass\n\ndef g():\n    ...\n'
    res = check_vacuity_stub(src)
    assert res.ok is False
    assert res.reason


def test_notimplemented_stub_rejected():
    res = check_vacuity_stub('def f():\n    raise NotImplementedError\n')
    assert res.ok is False


def test_docstring_only_body_is_stub():
    res = check_vacuity_stub('def f():\n    "does nothing"\n')
    assert res.ok is False


def test_real_function_accepted():
    assert check_vacuity_stub(REAL).ok is True


def test_real_work_with_api_named_test_tool_accepted():
    src = 'def test_tool(name):\n    found = name.strip().lower()\n    return found\n'
    assert check_vacuity_stub(src).ok is True


def test_vacuity_unparseable_fail_closed():
    assert check_vacuity_stub('def broken(:\n').ok is False


def test_complexity_floor_below_rejected():
    res = check_complexity_floor('def f():\n    return 1\n', {'FunctionDef': 2})
    assert res.ok is False


def test_complexity_floor_met_accepted():
    assert check_complexity_floor(REAL, {'FunctionDef': 2}).ok is True


def test_complexity_floor_docstring_not_counted():
    src = 'def f():\n    "doc"\n    return 1\n'
    assert check_complexity_floor(src, {'FunctionDef': 2}).ok is False


def test_exception_swallow_rejected():
    src = 'try:\n    work()\nexcept Exception:\n    pass\n'
    res = check_no_exception_swallow(src)
    assert res.ok is False


def test_exception_reraise_accepted():
    src = 'try:\n    work()\nexcept ValueError:\n    raise\n'
    assert check_no_exception_swallow(src).ok is True


def test_exception_handled_accepted():
    src = 'try:\n    work()\nexcept OSError as e:\n    log(e)\n'
    assert check_no_exception_swallow(src).ok is True


def test_swallow_unparseable_fail_closed():
    assert check_no_exception_swallow('try:\n').ok is False
