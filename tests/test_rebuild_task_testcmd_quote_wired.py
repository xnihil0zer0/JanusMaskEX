"""RED oracle: build_unit_task must SHELL-QUOTE the TEST-FILE paths it splices
into the scoped ``test_cmd`` portion of the ``verification_command`` (run later
via ``shell=True``).

THE BUG (CWE-78, follow-up to the f3a7320 oracle_cmd fix): inside
``harness/rebuild/task.py`` ``build_unit_task`` computes

    whole_file_args = ' '.join(_gate_tfs)          # task.py ~line 515

where ``_gate_tfs`` is ``_module_test_files(...)`` or, as a fallback,
``descriptor.test_files`` -- TARGET-REPO-RELATIVE test-file paths. That raw
string is interpolated UNQUOTED into ``test_cmd``:

    elif whole_file_args:
        test_cmd = f'{test_py} -m pytest {whole_file_args} -q'   # ~line 565-566

and, when the module's generated oracle / importing tests match, into
``sel_args``:

    if _module_tfs:
        sel_args = f'{whole_file_args} -k {_kexpr}'              # ~line 538

``test_cmd`` becomes part of the task's ``verification_command``, which the
harness runs under ``shell=True`` (loop.py:1330/1347, orchestrator.py:3142).
A target whose test-file path is ``t.py; touch pwned #`` therefore injects an
arbitrary shell command: the ``;`` terminates the pytest invocation and the rest
runs as a separate command. (``_k_expr`` is ALREADY single-quoted at task.py:359-403
and is NOT the vector; the unquoted value is the test-file path.)

THE CONTRACT this oracle pins: after shell tokenization (``shlex.split``), each
injected test-file path must survive as a SINGLE argument token equal to the
literal input -- the shell must NOT see an injected command separator. Equivalent
to: every test-file path spliced into ``whole_file_args`` passes through
``shlex.quote``.

RED today: the unquoted payload makes ``shlex.split`` yield separate ``touch`` /
``pwned`` tokens (a bare ``;`` survives outside any quote). GREEN after the fix:
the whole payload is one pytest path-argument token and no ``touch``/standalone
``;`` token appears.
"""
from __future__ import annotations

import shlex

import pytest

from harness.rebuild.harvest import Unit
from harness.rebuild.target import TargetDescriptor
from harness.rebuild.task import build_unit_task

PARENT_ROOT = "/home/op/JanusMaskJR"

# A path-injection payload: a bare ``;`` (no surrounding quote in the vulnerable
# build) terminates the pytest invocation; ``touch`` would run as its own command.
INJECT = "t.py; touch /tmp/pwned_testcmd #"


def _build(
    *,
    test_files: list[str],
    unit_test_selector: str = "",
    module_rel: str = "pkg/mod.py",
    unit_name: str = "add",
) -> dict:
    descriptor = TargetDescriptor(
        name="t",
        source_root="/tmp/src",
        modules=[module_rel],
        test_files=test_files,
        output_dir="/tmp/out",
        stash_dir="/tmp/stash",
        unit_test_selector=unit_test_selector,
    )
    unit = Unit(
        module=module_rel, name=unit_name, qualname=f"{module_rel}:{unit_name}",
        signature=f"def {unit_name}(a: int, b: int) -> int",
        docstring=None, decorators=[],
    )
    return build_unit_task(
        descriptor=descriptor, unit=unit, module_rel=module_rel,
        oracle_original_path="/tmp/orig.py",
        sibling_signatures=[], unit_test_text="",
        parent_root=PARENT_ROOT,
    )


def _no_injection(vcmd: str, inject: str) -> None:
    """Assert the injected test-file path is neutralized as one shell token.

    NOTE: a well-formed ``sel_args`` test_cmd legitimately contains ``;`` from its
    own exit-5 fallback scaffolding (``-q; __rc=$?; ... exit $__rc``), so we do NOT
    forbid ``;`` globally -- we assert the ATTACKER's payload (which carries its own
    ``;`` + ``touch``) survives intact as a SINGLE token, i.e. its separator never
    escapes into the shell as a standalone token.
    """
    tokens = shlex.split(vcmd)
    # the whole payload survives as ONE pytest path-argument token
    assert inject in tokens, (
        "test-file path must be a single shell token (shlex.quote'd); got: %r" % tokens
    )
    # the injected command never appears as a standalone shell token
    assert "touch" not in tokens, "injected 'touch' leaked as a shell token: %r" % tokens
    # the injected separator is INSIDE the quoted token, never a bare ``;`` token
    assert ";" not in tokens, "a bare ';' separator leaked as a shell token: %r" % tokens
    # the payload is emitted exactly once, shlex.quote'd, in the raw command string
    assert shlex.quote(inject) in vcmd, (
        "payload was not shlex.quote'd into the command: %r" % vcmd
    )


def test_whole_file_args_path_injection_is_neutralized():
    # No selector -> the ``elif whole_file_args:`` branch (~task.py:565-566) emits
    # ``... -m pytest {whole_file_args} -q``; whole_file_args == the raw test path.
    task = _build(test_files=[INJECT])
    _no_injection(task["verification_command"], INJECT)


def test_sel_args_module_scoped_path_injection_is_neutralized():
    # When the test-file basename matches the module's generated oracle
    # (``test_<stem>_generated.py``), _module_test_files keeps it (basename match,
    # no file read) so _module_tfs is non-empty and the selector branch builds
    # ``sel_args = f'{whole_file_args} -k {_kexpr}'`` (~task.py:538). The payload
    # rides in via whole_file_args; _k_expr is already quoted and is not the vector.
    inject = "evil; touch /tmp/pwned_sel #/test_mod_generated.py"
    task = _build(
        test_files=[inject],
        unit_test_selector="test_x.py -k {unit}",
        module_rel="mod.py",
    )
    _no_injection(task["verification_command"], inject)


def test_multiple_test_files_each_quoted():
    # A benign sibling path + a malicious path: each must be an independent token;
    # the benign one stays literally itself and the malicious one is neutralized.
    benign = "tests/test_mod.py"
    task = _build(test_files=[benign, INJECT])
    vcmd = task["verification_command"]
    tokens = shlex.split(vcmd)
    assert benign in tokens, "benign sibling path mangled: %r" % tokens
    _no_injection(vcmd, INJECT)


def test_benign_command_still_well_formed():
    # Regression: a normal test-file path yields a runnable, correctly-shaped
    # pytest command (no behavioral change for legitimate inputs).
    task = _build(test_files=["tests/test_mod.py"])
    vcmd = task["verification_command"]
    tokens = shlex.split(vcmd)
    assert "pytest" in tokens, "pytest invocation missing: %r" % tokens
    pi = tokens.index("pytest")
    # the test path follows ``-m pytest`` as a single literal token
    assert "tests/test_mod.py" in tokens, "benign test path missing: %r" % tokens
    # and ``-q`` is still present (well-formed pytest call)
    assert "-q" in tokens, "-q flag missing from benign command: %r" % tokens
    assert pi >= 2 and tokens[pi - 1] == "-m"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-x", "-q"]))
