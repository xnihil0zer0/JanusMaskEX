"""Gap-B oracle: sink-signature-aware PoC payloads (ngv2.poc_writer renderers).

RED on current HEAD, GREEN after applying EDITS.py.

Background (verified against ngv2/detonation.py + ngv2/poc_runner_live.py):
a PoC is 'confirmed' iff exit 0 AND the success marker ('VULNERABLE') is on
stdout/stderr AND the expected fs-signature ('pwned_marker') appears in the
work_dir before/after fs-diff. The diff is computed over CWD (the jail's
--chdir work_dir), so the marker must be a CWD-RELATIVE file whose path contains
'pwned_marker', written BY the real sink call -- not by an unconditional trailing
open() that fires even when the exploit failed (a false-confirm hazard).

This oracle asserts, per CWE template:
  1. the rendered Python PoC drives the marker write THROUGH the sink call shape
     that the real-world sink actually exposes (argv list for execve command
     sinks; reduce gadget for deser; etc.);
  2. the false-confirming UNCONDITIONAL trailing `open('pwned_marker','w')` is
     gone (the bare fs-signature filename is no longer written without the sink);
  3. (executable) the CWE-78 argv payload and the CWE-94 blanked-builtins gadget
     payload, when run against a mock sink, actually create a 'pwned_marker*'
     file -- proving the call shape works, not just that a string is present;
  4. (fail-closed honesty) the CWE-94 gadget does NOT escape a TRUE
     RestrictedPython compile_restricted -- so we never fake reproduction against
     a genuinely guarded sandbox (skipped if RestrictedPython is unavailable).

Run:  pytest _autowork_scratch/gapfix/B_payloads/test_sink_aware_payloads.py -q
(needs NobleGreedv2 on sys.path; the fixtures add it.)
"""
import os
import re
import sys

import pytest

# Put NobleGreedv2 on sys.path so `import ngv2...` resolves regardless of CWD.
_NGV2_ROOT = "/home/xnihil0zer0/NobleGreedv2"
if _NGV2_ROOT not in sys.path:
    sys.path.insert(0, _NGV2_ROOT)

from ngv2.contracts import Finding, PoC, Target  # noqa: E402
from ngv2 import poc_writer  # noqa: E402
from ngv2.poc_writer import (  # noqa: E402
    MARKER,
    FS_SIGNATURE,
    ground_finding,
    synthesize,
    write_poc,
)

# cwe -> (svc.py source exposing the real sink, real sink symbol, category alias)
CASES = {
    "CWE-78": (
        "import subprocess\n\n"
        "def run_cmd(argv):\n"
        "    # execve sink: argv passed straight through, NO shell\n"
        "    return subprocess.run(argv)\n",
        "run_cmd",
        "command_injection",
    ),
    "CWE-94": (
        "def run_user_code(snippet):\n"
        "    return eval(snippet)\n",
        "run_user_code",
        "sandbox_escape",
    ),
    "CWE-22": (
        "import os\n\n"
        "def read_file(path):\n"
        "    return open(os.path.join('/srv/data', path)).read()\n",
        "read_file",
        "path_traversal",
    ),
    "CWE-918": (
        "import urllib.request\n\n"
        "def fetch(url):\n"
        "    return urllib.request.urlopen(url).read()\n",
        "fetch",
        "ssrf",
    ),
    "CWE-89": (
        "def find_user(q):\n"
        "    return CURSOR.execute('SELECT * FROM u WHERE n=' + q)\n",
        "find_user",
        "sql_injection",
    ),
    "CWE-502": (
        "import pickle\n\n"
        "def load_blob(blob):\n"
        "    return pickle.loads(blob)\n",
        "load_blob",
        "deserialization",
    ),
}


def _write_target(tmp_path, source):
    svc = tmp_path / "svc.py"
    svc.write_text(source)
    return str(svc)


def _finding(svc_path, category, cwe):
    return Finding(
        id="F1", target=os.path.dirname(svc_path), category=category,
        severity="high", title=f"{cwe} finding", description=f"vuln {cwe}",
        evidence=[f"{svc_path}:2"],
    )


def _target(tmp_path):
    return Target(
        repo_url="https://example/x", repo_root=str(tmp_path),
        pinned_commit="deadbeef", language="python", loc=10,
    )


def _py_code(tmp_path, cwe):
    source, sym, _alias = CASES[cwe]
    svc = _write_target(tmp_path, source)
    art = synthesize(_finding(svc, cwe, cwe), _target(tmp_path))
    return art.python.code, sym


# ---------------------------------------------------------------------------
# (2) The false-confirming UNCONDITIONAL trailing marker write must be gone.
# ---------------------------------------------------------------------------
# On HEAD several templates end with `open('pwned_marker', 'w').close()` (or
# `open('{fs}',...)`) that writes the bare fs-signature regardless of whether
# the sink fired. After the fix, the only marker file the PoC writes is a
# *suffixed* CWD-relative name (pwned_marker_<cwe>) and it rides through the sink.

_UNCONDITIONAL_BARE_OPEN = re.compile(
    r"""open\(\s*['"]pwned_marker['"]\s*,\s*['"]w['"]\s*\)\s*\.close\(\)"""
)


@pytest.mark.parametrize("cwe", ["CWE-22", "CWE-918", "CWE-89", "CWE-78"])
def test_no_unconditional_bare_marker_open(tmp_path, cwe):
    code, _sym = _py_code(tmp_path, cwe)
    assert not _UNCONDITIONAL_BARE_OPEN.search(code), (
        f"{cwe}: still writes the bare fs-signature unconditionally "
        f"(false-confirm hazard):\n{code}"
    )


# ---------------------------------------------------------------------------
# (1) Each template drives the marker through the REAL sink call shape, and
#     writes a CWD-relative suffixed signature.
# ---------------------------------------------------------------------------
def test_cwe78_emits_argv_list_for_execve_sink(tmp_path):
    code, sym = _py_code(tmp_path, "CWE-78")
    # an argv LIST is passed to the sink (execve / create_subprocess_exec shape)
    assert "sys.executable" in code, code
    assert re.search(r"argv\s*=\s*\[", code), code
    assert f"{sym}(argv)" in code, code
    # the marker write is a suffixed CWD-relative file
    assert "pwned_marker_cmdexec" in code, code
    # shell-string fallback still kept (pins from test_poc_writer_wired)
    assert "; echo VULNERABLE" in code and ": > pwned_marker" in code, code


def test_cwe94_emits_blanked_builtins_gadget(tmp_path):
    code, sym = _py_code(tmp_path, "CWE-94")
    # the catch_warnings -> _module.__builtins__ open gadget (defeats naive
    # eval(code, {'__builtins__': {}})) must be in the payload, routed via the sink
    assert "catch_warnings" in code, code
    assert "_module.__builtins__" in code, code
    assert f"{sym}(" in code, code
    assert "pwned_marker_codeexec" in code, code


def test_cwe22_marker_rides_through_sink(tmp_path):
    code, sym = _py_code(tmp_path, "CWE-22")
    assert "pwned_marker_traversal" in code, code
    assert f"{sym}(" in code, code


def test_cwe502_reduce_gadget_writes_relative_marker(tmp_path):
    code, sym = _py_code(tmp_path, "CWE-502")
    assert "__reduce__" in code and "os.system" in code, code
    assert "pwned_marker_deser" in code, code
    # the gadget's command must create a CWD-relative file (touch), not just
    # a shell redirect that may not run in the deser sink context
    assert "touch pwned_marker_deser" in code, code
    assert f"{sym}(blob)" in code, code


def test_cwe918_and_cwe89_drop_suffixed_signature(tmp_path):
    ssrf, _ = _py_code(tmp_path, "CWE-918")
    assert "pwned_marker_ssrf" in ssrf and "169.254" in ssrf, ssrf
    sqli, _ = _py_code(tmp_path, "CWE-89")
    assert "pwned_marker_sqli" in sqli, sqli


# ---------------------------------------------------------------------------
# (3) Executable proof: the argv payload and the gadget payload, run against a
#     mock sink, actually create a pwned_marker* file under CWD.
# ---------------------------------------------------------------------------
def test_cwe78_argv_payload_executes_and_writes_marker(tmp_path, monkeypatch):
    code, _sym = _py_code(tmp_path, "CWE-78")
    monkeypatch.chdir(tmp_path)
    # Run the generated PoC body against a REAL execve sink (subprocess.run) by
    # writing the svc target into CWD so `from svc import run_cmd` resolves.
    (tmp_path / "svc.py").write_text(CASES["CWE-78"][0])
    rc = os.system(f"{sys.executable} -c {_shquote(code)}")
    assert rc == 0, "PoC body crashed"
    produced = [p for p in os.listdir(tmp_path) if "pwned_marker" in p]
    assert produced, f"argv sink did not write a marker; dir={os.listdir(tmp_path)}"


def test_cwe94_gadget_escapes_naive_blanked_builtins(tmp_path, monkeypatch):
    """The gadget defeats a NAIVE eval(code, {'__builtins__': {}}) sandbox
    (misconfigured / non-AST-transforming restriction)."""
    code, _sym = _py_code(tmp_path, "CWE-94")
    monkeypatch.chdir(tmp_path)
    # svc with a NAIVE restricted-eval sink (blanked builtins, no AST transform)
    (tmp_path / "svc.py").write_text(
        "def run_user_code(snippet):\n"
        "    return eval(compile(snippet, '<r>', 'eval'), {'__builtins__': {}}, {})\n"
    )
    rc = os.system(f"{sys.executable} -c {_shquote(code)}")
    assert rc == 0
    produced = [p for p in os.listdir(tmp_path) if "pwned_marker" in p]
    assert produced, (
        "gadget did not escape the naive blanked-builtins sandbox; "
        f"dir={os.listdir(tmp_path)}"
    )


# ---------------------------------------------------------------------------
# (4) Fail-closed honesty: against TRUE RestrictedPython the gadget must NOT
#     write the marker -- we never fake reproduction of a guarded sandbox.
# ---------------------------------------------------------------------------
def test_cwe94_failclosed_against_true_restrictedpython(tmp_path, monkeypatch):
    RP = pytest.importorskip("RestrictedPython")
    from RestrictedPython import compile_restricted, safe_globals  # noqa: F401
    code, _sym = _py_code(tmp_path, "CWE-94")
    monkeypatch.chdir(tmp_path)
    # svc with a TRUE compile_restricted two-step sink
    (tmp_path / "svc.py").write_text(
        "from RestrictedPython import compile_restricted, safe_globals\n"
        "def run_user_code(snippet):\n"
        "    code = compile_restricted(snippet, '<r>', 'eval')\n"
        "    return eval(code, dict(safe_globals), {})\n"
    )
    os.system(f"{sys.executable} -c {_shquote(code)}")
    produced = [p for p in os.listdir(tmp_path) if "pwned_marker" in p]
    assert not produced, (
        "FALSE REPRODUCTION: gadget wrote a marker against a TRUE "
        "compile_restricted sandbox -- this would be a faked confirmation. "
        f"dir={os.listdir(tmp_path)}"
    )


def _shquote(s: str) -> str:
    import shlex
    return shlex.quote(s)
