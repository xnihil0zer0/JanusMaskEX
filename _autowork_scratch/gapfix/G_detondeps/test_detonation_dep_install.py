"""Hermetic RED->GREEN oracle for the missing-dep install fallback in
``ngv2.poc_runner_live.detonate_live``.

No real network / pip / bwrap: a fake ``jail_runner`` scripts the per-run
(exit_code, stdout, stderr) and a fake ``pip_installer`` records install requests
and reports success/failure. Pins:

(a) a first run failing with ModuleNotFoundError triggers exactly one install of
    the named module and a single retry;
(b) a run that succeeds first time installs nothing and never retries;
(c) pip failure degrades to the original failure (no raise, no false positive);
(d) the install loop is bounded;
(e) a missing module equal to the target's own top package does NOT trigger
    install.

The existing detonation/poc_runner oracles must remain green (these seams are
optional with real-path defaults).
"""
import os

from ngv2.contracts import PoC
import ngv2.poc_runner_live as prl


def _poc():
    return PoC(finding_id='F1', language='python', code='print("hi")', entrypoint='main')


def _mnfe(name):
    return (
        "Traceback (most recent call last):\n"
        "  File \"poc.py\", line 4, in <module>\n"
        "    from nltk.classify.megam import call_megam\n"
        f"ModuleNotFoundError: No module named '{name}'\n"
    )


class _Pip:
    """Records (name, target_dir) requests; configurable per-name success."""

    def __init__(self, fail=()):
        self.calls = []
        self._fail = set(fail)

    def __call__(self, name, target_dir):
        self.calls.append((name, target_dir))
        return name not in self._fail


def _scripted_jail_runner(scripts):
    """scripts: list of dicts returned in order; PYTHONPATH of each call recorded."""
    calls = {"n": 0, "pythonpaths": [], "extra_ro": []}

    def runner(cmd, *, repo_root, work_dir, extra_ro, child_env, timeout_s):
        idx = min(calls["n"], len(scripts) - 1)
        calls["pythonpaths"].append(child_env.get("PYTHONPATH", ""))
        calls["extra_ro"].append(list(extra_ro))
        calls["n"] += 1
        return dict(scripts[idx])

    return runner, calls


# ---------------------------------------------------------------------------
# (a) first-run MNFE triggers exactly one install + one retry
# ---------------------------------------------------------------------------
def test_missing_dep_triggers_single_install_and_retry():
    pip = _Pip()
    runner, calls = _scripted_jail_runner([
        {"exit_code": 1, "stdout": "", "stderr": _mnfe("regex"), "timed_out": False},
        {"exit_code": 0, "stdout": "VULNERABLE", "stderr": "", "timed_out": False},
    ])
    res = prl.detonate_live(
        _poc(), {}, pip_installer=pip, jail_runner=runner,
    )
    assert [n for n, _ in pip.calls] == ["regex"], "exactly one install of 'regex'"
    # pip installs into the work_dir's _jmdeps staging dir.
    assert os.path.basename(pip.calls[0][1]) == prl.JMDEPS_DIRNAME
    assert calls["n"] == 2, "exactly one retry"
    assert res["exit_code"] == 0
    # The retry's env must carry the staged deps dir on PYTHONPATH.
    assert prl.JMDEPS_DIRNAME in calls["pythonpaths"][1]
    # ...and the deps dir bound RO into the retry jail.
    assert any(prl.JMDEPS_DIRNAME in p for p in calls["extra_ro"][1])


# ---------------------------------------------------------------------------
# (b) first-time success installs nothing, no retry
# ---------------------------------------------------------------------------
def test_success_first_run_installs_nothing():
    pip = _Pip()
    runner, calls = _scripted_jail_runner([
        {"exit_code": 0, "stdout": "VULNERABLE", "stderr": "", "timed_out": False},
    ])
    res = prl.detonate_live(_poc(), {}, pip_installer=pip, jail_runner=runner)
    assert pip.calls == []
    assert calls["n"] == 1
    assert res["exit_code"] == 0


# ---------------------------------------------------------------------------
# (c) pip failure degrades to the original failure (no raise, no FP)
# ---------------------------------------------------------------------------
def test_pip_failure_degrades_to_original_failure():
    pip = _Pip(fail={"regex"})
    runner, calls = _scripted_jail_runner([
        {"exit_code": 1, "stdout": "", "stderr": _mnfe("regex"), "timed_out": False},
    ])
    res = prl.detonate_live(
        _poc(), {}, pip_installer=pip, jail_runner=runner,
        success_marker="VULNERABLE", expected_fs_signature="A pwned.txt",
    )
    assert pip.calls == [("regex", pip.calls[0][1])]  # attempted once
    assert calls["n"] == 1, "no retry after pip failure"
    assert res["exit_code"] == 1
    # No false positive: a failed run cannot be 'confirmed'.
    assert res["verdict"] != "confirmed"


def test_pip_installer_never_raises_into_caller():
    def boom(name, target_dir):
        raise RuntimeError("infra blew up")

    runner, calls = _scripted_jail_runner([
        {"exit_code": 1, "stdout": "", "stderr": _mnfe("regex"), "timed_out": False},
    ])
    # The seam contract is fail-soft (returns bool); but defend the loop anyway:
    # a raising installer must not propagate out of detonate_live.
    try:
        res = prl.detonate_live(_poc(), {}, pip_installer=boom, jail_runner=runner)
    except Exception as exc:  # pragma: no cover - this is the failure we guard
        raise AssertionError(f"detonate_live must not raise on installer error: {exc!r}")
    assert res["exit_code"] == 1


# ---------------------------------------------------------------------------
# (d) install loop is bounded
# ---------------------------------------------------------------------------
def test_install_loop_is_bounded():
    pip = _Pip()
    # Every run surfaces a brand-new missing module -> would loop forever if
    # unbounded. Provide more scripts than the cap.
    chain = ["m0", "m1", "m2", "m3", "m4", "m5"]
    scripts = [
        {"exit_code": 1, "stdout": "", "stderr": _mnfe(name), "timed_out": False}
        for name in chain
    ]
    runner, calls = _scripted_jail_runner(scripts)
    res = prl.detonate_live(_poc(), {}, pip_installer=pip, jail_runner=runner)
    # First run + at most MAX_DEP_INSTALL_ROUNDS retries.
    assert calls["n"] <= 1 + prl.MAX_DEP_INSTALL_ROUNDS
    assert len(pip.calls) <= prl.MAX_DEP_INSTALL_ROUNDS
    assert res["exit_code"] == 1


# ---------------------------------------------------------------------------
# (e) target's own top package does NOT trigger install
# ---------------------------------------------------------------------------
def test_target_own_package_not_installed(tmp_path):
    # Build a fake target repo whose top package is 'nltk'.
    repo = tmp_path / "nltk_repo"
    (repo / "nltk").mkdir(parents=True)
    (repo / "nltk" / "__init__.py").write_text("# target package\n")
    pip = _Pip()
    runner, calls = _scripted_jail_runner([
        {"exit_code": 1, "stdout": "", "stderr": _mnfe("nltk"), "timed_out": False},
    ])
    res = prl.detonate_live(
        _poc(), {"repo_root": str(repo)}, pip_installer=pip, jail_runner=runner,
    )
    assert pip.calls == [], "must not pip-install the target's own package"
    assert calls["n"] == 1, "no retry for an own-package import error"
    assert res["exit_code"] == 1


def test_third_party_installed_even_with_repo_root(tmp_path):
    # Same repo, but the missing module is a genuine third-party dep ('regex').
    repo = tmp_path / "nltk_repo2"
    (repo / "nltk").mkdir(parents=True)
    (repo / "nltk" / "__init__.py").write_text("# target package\n")
    pip = _Pip()
    runner, calls = _scripted_jail_runner([
        {"exit_code": 1, "stdout": "", "stderr": _mnfe("regex"), "timed_out": False},
        {"exit_code": 0, "stdout": "VULNERABLE", "stderr": "", "timed_out": False},
    ])
    res = prl.detonate_live(
        _poc(), {"repo_root": str(repo)}, pip_installer=pip, jail_runner=runner,
    )
    assert [n for n, _ in pip.calls] == ["regex"]
    assert res["exit_code"] == 0


# ---------------------------------------------------------------------------
# helper-level pin: parser reduces dotted names to top-level and dedups.
# ---------------------------------------------------------------------------
def test_missing_modules_parser():
    err = _mnfe("regex.foo") + _mnfe("regex.bar") + _mnfe("numpy")
    assert prl._missing_modules_from_stderr(err) == ["regex", "numpy"]
    assert prl._missing_modules_from_stderr("no error here") == []
