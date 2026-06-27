"""Hermetic RED oracle for taint-aware sink localization (Gap H).

Proves the fix for the empty-hunt fallback MIS-LOCALIZING the sink: when a
scanner regex hit lands inside a function, the candidate used to attach the
*enclosing def* as the callable entrypoint regardless of whether that function
actually forwards its parameters into the dangerous call. The triton
``create_dockerfile_linux`` class of bug (a function that builds a Dockerfile
*string* from literals and runs a fixed build command) produced PoCs that
``poc_authenticity`` correctly rejected -- wasted hunts.

These tests FAIL on HEAD (no ``ngv2.sink_localize`` module; the fallback keeps
non-forwarding candidates and poc_writer grounds on the wrong symbol) and PASS
after the edits in EDITS.md are applied.

Pure: no network, no agy, no state/. Fixtures are written to tmp dirs; the agy
``complete`` seam is faked to return ``[]`` so the deterministic fallback runs.
"""
from __future__ import annotations

import importlib

import pytest


# --------------------------------------------------------------------------
# Part 1: the taint-forwarding analyzer module (ngv2.sink_localize)
# --------------------------------------------------------------------------

def _load_sink_localize():
    try:
        return importlib.import_module("ngv2.sink_localize")
    except Exception as exc:  # pragma: no cover - explicit RED on HEAD
        pytest.fail("ngv2.sink_localize not importable yet: {0!r}".format(exc))


_FORWARDING_SUBPROCESS = (
    "import subprocess\n"
    "def run_cmd(user_arg):\n"
    "    subprocess.run(user_arg, shell=True)\n"
)

# create_dockerfile_linux-style: subprocess fed ONLY a module-global template /
# literal; the function's parameters never touch the dangerous call.
_NONFORWARDING_DOCKERFILE = (
    "import subprocess\n"
    "DOCKERFILE = 'FROM ubuntu:22.04\\nRUN apt-get update\\n'\n"
    "def create_dockerfile_linux(version, args):\n"
    "    content = DOCKERFILE\n"
    "    with open('Dockerfile', 'w') as fh:\n"
    "        fh.write(content)\n"
    "    subprocess.Popen(['docker', 'build', '.'])\n"
    "    return content\n"
)

_FORWARDING_EVAL = (
    "def compute(expr):\n"
    "    result = eval(expr)\n"
    "    return result\n"
)

# forwarding via a local + f-string (chained data flow)
_FORWARDING_CHAINED = (
    "import os\n"
    "def handler(name):\n"
    "    cmd = 'ls ' + name\n"
    "    full = f'{cmd} -la'\n"
    "    os.system(full)\n"
)


def test_forwarding_subprocess_is_high_confidence(tmp_path):
    sl = _load_sink_localize()
    f = tmp_path / "cmd.py"
    f.write_text(_FORWARDING_SUBPROCESS)
    loc = sl.localize_sink(str(f), 3, "subprocess.run")
    assert loc["symbol"] == "run_cmd"
    assert loc["forwarding"] is True
    assert loc["confidence"] == "high"


def test_dockerfile_template_is_low_confidence(tmp_path):
    sl = _load_sink_localize()
    f = tmp_path / "build.py"
    f.write_text(_NONFORWARDING_DOCKERFILE)
    loc = sl.localize_sink(str(f), 7, "subprocess.Popen")
    # Enclosing function exists but NONE of its params reach the sink argv.
    assert loc["symbol"] == "create_dockerfile_linux"
    assert loc["forwarding"] is False
    assert loc["confidence"] == "low"


def test_eval_forwarding_is_high_confidence(tmp_path):
    sl = _load_sink_localize()
    f = tmp_path / "ev.py"
    f.write_text(_FORWARDING_EVAL)
    loc = sl.localize_sink(str(f), 2, "eval")
    assert loc["symbol"] == "compute"
    assert loc["forwarding"] is True
    assert loc["confidence"] == "high"


def test_chained_local_dataflow_forwards(tmp_path):
    sl = _load_sink_localize()
    f = tmp_path / "chain.py"
    f.write_text(_FORWARDING_CHAINED)
    loc = sl.localize_sink(str(f), 5, "os.system")
    assert loc["symbol"] == "handler"
    assert loc["forwarding"] is True
    assert loc["confidence"] == "high"


def test_module_level_sink_is_unknown(tmp_path):
    sl = _load_sink_localize()
    f = tmp_path / "mod.py"
    f.write_text("import os\nos.system('echo hi')\n")
    loc = sl.localize_sink(str(f), 2, "os.system")
    assert loc["symbol"] == ""
    assert loc["confidence"] == "unknown"


def test_deterministic_across_runs(tmp_path):
    sl = _load_sink_localize()
    f = tmp_path / "build.py"
    f.write_text(_NONFORWARDING_DOCKERFILE)
    first = sl.localize_sink(str(f), 7, "subprocess.Popen")
    for _ in range(5):
        assert sl.localize_sink(str(f), 7, "subprocess.Popen") == first


def test_failsoft_on_unparseable_file(tmp_path):
    sl = _load_sink_localize()
    f = tmp_path / "broken.py"
    f.write_text("def oops(:\n    subprocess.run(x\n")  # syntax error
    loc = sl.localize_sink(str(f), 2, "subprocess.run")
    # Never raises; neutral 'unknown' so the caller keeps current behavior.
    assert loc["confidence"] == "unknown"
    assert loc["forwarding"] is False


def test_failsoft_on_missing_file():
    sl = _load_sink_localize()
    loc = sl.localize_sink("/no/such/file/xyz.py", 1, "eval")
    assert loc["confidence"] == "unknown"


# --------------------------------------------------------------------------
# Part 2: the hunt fallback uses taint forwarding to order/drop candidates
# --------------------------------------------------------------------------

def _fake_complete_empty(messages, **kwargs):
    return "[]"


def _write_mixed_repo(tmp_path):
    """A repo with one forwarding sink and one create_dockerfile_linux-style
    non-forwarding sink, plus a forwarding eval."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "good_cmd.py").write_text(_FORWARDING_SUBPROCESS)
    (repo / "build.py").write_text(_NONFORWARDING_DOCKERFILE)
    (repo / "ev.py").write_text(_FORWARDING_EVAL)
    return str(repo)


def test_fallback_drops_nonforwarding_dockerfile(tmp_path):
    hlc = importlib.import_module("ngv2.hunt_lead_client")
    repo = _write_mixed_repo(tmp_path)
    client = hlc.make_hunt_lead_client(complete=_fake_complete_empty)
    cands = client(target="t", context={"repo": repo})["candidates"]
    assert cands, "fallback must surface forwarding candidates"
    syms_in_evidence = {c["evidence"][0] for c in cands}
    # The non-forwarding create_dockerfile_linux sink (build.py) must be dropped
    # (or at minimum deprioritized below the forwarding ones).
    build_hits = [c for c in cands if c["evidence"][0].startswith("build.py")]
    assert not build_hits, "non-forwarding dockerfile sink must be dropped"
    # Forwarding subprocess + eval survive.
    assert any(c["evidence"][0].startswith("good_cmd.py") for c in cands)
    assert any(c["evidence"][0].startswith("ev.py") for c in cands)


def test_fallback_pins_forwarding_entrypoint_symbol(tmp_path):
    hlc = importlib.import_module("ngv2.hunt_lead_client")
    repo = _write_mixed_repo(tmp_path)
    client = hlc.make_hunt_lead_client(complete=_fake_complete_empty)
    cands = client(target="t", context={"repo": repo})["candidates"]
    cmd = next(c for c in cands if c["evidence"][0].startswith("good_cmd.py"))
    # The forwarding function name is pinned so poc_writer grounds on it.
    assert cmd.get("sink_symbol") == "run_cmd"


def test_fallback_deterministic_ordering(tmp_path):
    hlc = importlib.import_module("ngv2.hunt_lead_client")
    repo = _write_mixed_repo(tmp_path)
    client = hlc.make_hunt_lead_client(complete=_fake_complete_empty)
    a = client(target="t", context={"repo": repo})["candidates"]
    b = client(target="t", context={"repo": repo})["candidates"]
    assert [c["evidence"] for c in a] == [c["evidence"] for c in b]
    assert [c["id"] for c in a] == [c["id"] for c in b]


# --------------------------------------------------------------------------
# Part 3: poc_writer grounds on the pinned forwarding symbol (sym origin)
# --------------------------------------------------------------------------

def test_poc_writer_grounds_on_pinned_symbol(tmp_path):
    """The PoC's `sym` originates in poc_writer.default_resolver. With the
    create_dockerfile_linux file, the OLD ranking picks create_dockerfile_linux
    (its body mentions subprocess). A finding that pins sink_symbol=run_real
    must instead ground on run_real."""
    pw = importlib.import_module("ngv2.poc_writer")
    src = (
        "import subprocess\n"
        "def create_dockerfile_linux(v):\n"          # noise: body mentions subprocess
        "    subprocess.Popen(['docker', 'build', '.'])\n"
        "    return 'FROM ubuntu'\n"
        "def run_real(user):\n"
        "    subprocess.run(user, shell=True)\n"
    )
    f = tmp_path / "mod.py"
    f.write_text(src)

    finding = {
        "id": "H1",
        "target": str(tmp_path),
        "category": "CWE-78",
        "severity": "high",
        "title": "cmd inj",
        "description": "",
        "evidence": ["mod.py:6"],
        "sink_name": "subprocess.run",
        "call_sites": ["subprocess.run(user, shell=True)"],
        "sink_symbol": "run_real",
    }
    # _repo_root accepts a directory-path string target.
    g = pw.ground_finding(finding, str(tmp_path))
    # entrypoint / first symbol is the pinned forwarding function, NOT the
    # noisy create_dockerfile_linux.
    assert g.symbols[0] == "run_real"
    assert g.entrypoint == "run_real"
