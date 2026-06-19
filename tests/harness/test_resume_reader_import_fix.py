"""Oracle for harness.tmux_worker._resume_pinned_session_enabled.

Pins the behaviour of the fail-safe flag reader by driving the REAL function
through its lazy ``from harness.orchestrator import load_config`` import. The
tests monkeypatch ``harness.orchestrator.load_config`` (the live loader the
function imports lazily) -- never ``harness.tmux_worker.load_config`` (no such
name) and never the reader itself -- so the in-function import at
``harness/tmux_worker.py:313`` is genuinely executed.

RED baseline: against the buggy ``from harness.config import load_config`` the
in-function import raises ``ModuleNotFoundError`` before the patched
orchestrator loader is reached; the bare ``except Exception: return False``
yields ``False`` and ``test_resume_reader_returns_true_when_flag_set`` fails.
GREEN once the import targets ``harness.orchestrator``.
"""
import importlib.util
import harness.orchestrator as orch
import harness.tmux_worker as tw

def test_resume_reader_returns_true_when_flag_set(monkeypatch):
    """RED->GREEN CORE: flag truthy -> True via the real lazy import."""
    monkeypatch.setattr(orch, 'load_config', lambda: {'workers': {'resume_pinned_session': True}})
    assert tw._resume_pinned_session_enabled() is True

def test_resume_reader_failsafe_flag_absent(monkeypatch):
    """FAIL-SAFE: missing ``resume_pinned_session`` key -> False."""
    monkeypatch.setattr(orch, 'load_config', lambda: {'workers': {}})
    assert tw._resume_pinned_session_enabled() is False

def test_resume_reader_failsafe_load_config_raises(monkeypatch):
    """FAIL-SAFE: a raising loader is swallowed -> False, no exception escapes."""

    def _boom():
        raise RuntimeError('boom')
    monkeypatch.setattr(orch, 'load_config', _boom)
    assert tw._resume_pinned_session_enabled() is False

def test_resume_reader_no_harness_config_module():
    """Guard against re-introduction of the missing ``harness.config`` module."""
    assert importlib.util.find_spec('harness.config') is None

def test_resume_reader_regression_real_import_path_executed_not_bypassed(monkeypatch):
    """The patched orchestrator loader must actually be invoked by the function.

    Records invocation through a sentinel: on the buggy ``from harness.config``
    import the function returns False without ever reaching the loader, so the
    recorder stays empty and this fails. After the fix the lazy
    ``from harness.orchestrator import load_config`` picks up the patch, the
    recorder fires, and the truthy flag flows through to True.
    """
    calls = []

    def _recording_loader():
        calls.append(True)
        return {'workers': {'resume_pinned_session': True}}
    monkeypatch.setattr(orch, 'load_config', _recording_loader)
    result = tw._resume_pinned_session_enabled()
    assert calls == [True]
    assert result is True

def test_resume_reader_regression_no_patch_of_tmux_worker_load_config_name():
    """The reader must not eagerly bind ``load_config`` in its own namespace.

    Confirms the loader is reachable only via the in-function lazy import (so
    patching ``harness.orchestrator.load_config`` is the correct seam) and that
    no module-level ``harness.tmux_worker.load_config`` name exists to patch.
    """
    assert not hasattr(tw, 'load_config')
    assert callable(tw._resume_pinned_session_enabled)