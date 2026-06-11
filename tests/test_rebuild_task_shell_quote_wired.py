"""RED oracle: build_unit_task must SHELL-QUOTE every value it splices into the
oracle ``verification_command`` (run later via ``shell=True``).

THE BUG (CWE-78, live-confirmed via the NobleGreed detonation pipeline 2026-06-11):
``harness/rebuild/task.py`` builds ``oracle_cmd`` by f-string-interpolating
``module_rel`` / ``oracle_original_path`` / ``unit.name`` / the ``parent_root``-derived
oracle.py + config paths directly into a shell command string with NO ``shlex.quote``.
``module_rel`` is a target-repo-relative module path; a target whose module path is
``m.py; touch pwned #`` injects an arbitrary command that runs when the harness
executes the ``verification_command`` under ``shell=True`` (loop.py:1330,
orchestrator.py:3142). A live PoC against the real ``build_unit_task`` printed
``VULNERABLE`` and dropped a file inside a bubblewrap detonation.

THE CONTRACT this oracle pins: the oracle command, after shell tokenization
(``shlex.split``), must carry each injected value as a SINGLE argument token equal to
the literal input -- the shell must NOT see an injected command separator. Equivalent
to: every interpolated value passes through ``shlex.quote``.

RED today: unquoted ``module_rel='m.py; touch pwned #'`` makes ``shlex.split`` yield
separate ``m.py``, ``touch``, ``pwned`` tokens (the ``;`` ends the python invocation).
GREEN after the fix: the whole payload is one ``--target`` argument token and no
``touch``/``;`` token appears.
"""
from __future__ import annotations

import shlex

import pytest

from harness.rebuild.harvest import Unit
from harness.rebuild.target import TargetDescriptor
from harness.rebuild.task import build_unit_task

PARENT_ROOT = "/home/op/JanusMaskJR"


def _vcmd(module_rel: str, oracle_original_path: str, unit_name: str = "add") -> str:
    descriptor = TargetDescriptor(
        name="t",
        source_root="/tmp/src",
        modules=[module_rel],
        test_files=[],            # no test gate -> vcmd is exactly oracle_cmd
        output_dir="/tmp/out",
        stash_dir="/tmp/stash",
        unit_test_selector="",
    )
    unit = Unit(
        module=module_rel, name=unit_name, qualname=f"{module_rel}:{unit_name}",
        signature=f"def {unit_name}(a: int, b: int) -> int",
        docstring=None, decorators=[],
    )
    task = build_unit_task(
        descriptor=descriptor, unit=unit, module_rel=module_rel,
        oracle_original_path=oracle_original_path,
        sibling_signatures=[], unit_test_text="",
        parent_root=PARENT_ROOT,
    )
    return task["verification_command"]


def test_module_rel_injection_is_neutralized():
    inject = "m.py; touch /tmp/pwned_xyz #"
    vcmd = _vcmd(inject, "/tmp/orig.py")
    tokens = shlex.split(vcmd)
    # the injected payload survives as ONE --target argument token
    assert inject in tokens, (
        "module_rel must be a single shell token (shlex.quote'd); got tokens: %r" % tokens
    )
    # and the injected command never appears as standalone shell tokens
    assert "touch" not in tokens, "injected 'touch' leaked as a shell token: %r" % tokens
    assert ";" not in vcmd.replace(shlex.quote(inject), ""), (
        "a command separator survived outside the quoted argument"
    )


def test_oracle_original_path_injection_is_neutralized():
    inject = "/tmp/orig.py; touch /tmp/pwned2 #"
    vcmd = _vcmd("clean_mod.py", inject)
    tokens = shlex.split(vcmd)
    assert inject in tokens, (
        "oracle_original_path must be a single shell token; got: %r" % tokens
    )
    assert "touch" not in tokens, "injected 'touch' leaked: %r" % tokens


def test_unit_name_injection_is_neutralized():
    # unit.name flows into --unit; a crafted name must not break out of its arg.
    inject = "add; touch /tmp/pwned3 #"
    vcmd = _vcmd("clean_mod.py", "/tmp/orig.py", unit_name=inject)
    tokens = shlex.split(vcmd)
    assert "touch" not in tokens, "injected 'touch' via unit.name leaked: %r" % tokens


def test_benign_command_still_well_formed():
    # Regression: a normal module path produces a runnable, correctly-shaped command.
    vcmd = _vcmd("pkg/mod.py", "/tmp/orig.py")
    tokens = shlex.split(vcmd)
    assert "python" in tokens[0] or tokens[0] == "python"
    assert "--target" in tokens
    ti = tokens.index("--target")
    assert tokens[ti + 1] == "pkg/mod.py"
    assert "--original" in tokens and "--unit" in tokens and "--config" in tokens


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-x", "-q"]))
