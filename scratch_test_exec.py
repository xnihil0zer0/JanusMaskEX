import sys
from harness.narrow_fuzz.validation import _exec_module

def test_exec_module_success():
    src = "def add(a, b): return a + b"
    ns = _exec_module("test_mod", src)
    assert ns is not None
    assert ns["__name__"] == "test_mod"
    assert ns["__file__"] == "<module test_mod>"
    assert "add" in ns
    assert ns["add"](1, 2) == 3

def test_exec_module_syntax_error():
    src = "def add(a, b"
    assert _exec_module("test_mod_syntax", src) is None

def test_exec_module_runtime_error():
    src = "raise ValueError('oops')"
    assert _exec_module("test_mod_runtime", src) is None

def test_exec_module_base_exception():
    src = "import sys; sys.exit(1)"
    assert _exec_module("test_mod_exit", src) is None

def test_exec_module_sys_modules_cleanup():
    module_name = "test_mod_cleanup"
    assert module_name not in sys.modules
    src = "x = 42"
    ns = _exec_module(module_name, src)
    assert ns is not None
    assert ns["x"] == 42
    assert module_name not in sys.modules

def test_exec_module_sys_modules_restore():
    module_name = "test_mod_restore"
    dummy = object()
    sys.modules[module_name] = dummy
    src = "x = 100"
    ns = _exec_module(module_name, src)
    assert ns is not None
    assert ns["x"] == 100
    assert sys.modules[module_name] is dummy
    del sys.modules[module_name]

def test_exec_module_relative_import_namespace():
    ns = _exec_module("a.b.c", "pass")
    assert ns is not None
    assert ns["__package__"] == "a.b"
