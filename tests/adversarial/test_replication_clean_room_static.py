"""REPL-10 adversarial — clean-room replication static guards.

Static (no live dispatch) assertions that a fresh clone at an arbitrary path
can bootstrap and self-fix with ZERO dependency on the per-machine
~/.claude/.../memory dir:

1. The 3 smoke artifacts are git-tracked.
2. The harness/ package is Path.home()-free (no ~ / HOME coupling).
3. bootstrap.sh seeds a deny-all (comment-only) autowork allowlist.
4. _build_agent_env sets CLAUDE_PROJECT_DIR — the bar that drives REPL-8; this
   assertion FAILS until the REPL-8 env-key edit lands (it has, so it is GREEN).

These run under the project's pytest invocation (no TUPLE marker, <120s).
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


# -- (1) smoke artifacts are git-tracked -------------------------------------


class TestSmokeArtifactsTracked:
    SMOKE_ARTIFACTS = (
        "brief_hooks_smoke.md",
        "plan_hooks_smoke.json",
        "harness/smoke_target.py",
    )

    def _tracked(self) -> set[str]:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return set(out.splitlines())

    @pytest.mark.parametrize("rel", SMOKE_ARTIFACTS)
    def test_smoke_artifact_is_tracked(self, rel: str) -> None:
        assert rel in self._tracked(), f"smoke artifact not git-tracked: {rel}"

    def test_smoke_plan_defines_smoke_version_task(self) -> None:
        plan = json.loads((_REPO_ROOT / "plan_hooks_smoke.json").read_text())
        ids = {t["task_id"] for t in plan["tasks"]}
        assert "SMOKE_VERSION" in ids, ids

    def test_committed_stub_omits_version_assignment(self) -> None:
        # The committed stub MUST NOT define a top-level __version__ assignment
        # so the first dispatch produces a real diff (and a real commit). The
        # docstring legitimately mentions "__version__", so check the AST for an
        # actual module-level assignment rather than a substring.
        tree = ast.parse((_REPO_ROOT / "harness" / "smoke_target.py").read_text())
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for t in targets:
                assert not (isinstance(t, ast.Name) and t.id == "__version__"), (
                    "committed smoke_target.py must omit the __version__ "
                    "assignment (else the smoke dispatch produces no_diff)"
                )


# -- (2) harness/ is Path.home()-free ----------------------------------------


def _home_dir_offenders(source: str) -> list[str]:
    """Return ``"<lineno>: <kind>"`` for each real CODE coupling to $HOME.

    AST-aware (C9.8): we walk the parsed tree and match the forbidden CODE
    constructs as AST nodes, so a docstring / comment / prose string that merely
    *mentions* ``Path.home()`` or ``$HOME`` (a string ``ast.Constant``) can never
    match a ``Call`` / ``Attribute`` / ``Subscript`` pattern -- it is structurally
    impossible to false-positive on prose, while every executable use is still
    caught. (The #33 trip was a ``deps.py`` docstring spelling the literal token
    under the old naive substring scan.)
    """

    def _str_const(node: ast.AST | None):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    offenders: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return offenders
    for node in ast.walk(tree):
        hit: str | None = None
        if isinstance(node, ast.Call):
            f = node.func
            # Path.home() / pathlib.Path.home()
            if isinstance(f, ast.Attribute) and f.attr == "home":
                base = f.value
                if isinstance(base, ast.Name) and base.id == "Path":
                    hit = "Path.home()"
                elif isinstance(base, ast.Attribute) and base.attr == "Path":
                    hit = "pathlib.Path.home()"
            # os.environ.get("HOME"...)
            if (
                hit is None
                and isinstance(f, ast.Attribute)
                and f.attr == "get"
                and isinstance(f.value, ast.Attribute)
                and f.value.attr == "environ"
                and node.args
                and _str_const(node.args[0]) == "HOME"
            ):
                hit = "os.environ.get('HOME')"
            # Path("~..."), pathlib.Path("~...")
            if hit is None:
                callee = f.attr if isinstance(f, ast.Attribute) else (
                    f.id if isinstance(f, ast.Name) else None
                )
                if callee == "Path" and node.args:
                    s = _str_const(node.args[0])
                    if isinstance(s, str) and s.startswith("~"):
                        hit = f"Path({s!r})"
        # os.path.expanduser (call or bare reference)
        if hit is None and isinstance(node, ast.Attribute) and node.attr == "expanduser":
            hit = "os.path.expanduser"
        # os.environ["HOME"]
        if hit is None and isinstance(node, ast.Subscript):
            v = node.value
            if isinstance(v, ast.Attribute) and v.attr == "environ":
                key = _str_const(node.slice)
                if key == "HOME":
                    hit = "os.environ['HOME']"
        if hit is not None:
            offenders.append(f"{getattr(node, 'lineno', '?')}: {hit}")
    return offenders


class TestHarnessHomeFree:
    # Coupling to the operator's $HOME is what breaks a clone. The harness
    # package must never resolve paths relative to the user home -- but the guard
    # is AST-aware so prose/docstrings that mention the tokens do not trip it.

    def test_harness_package_is_home_free(self) -> None:
        offenders: list[str] = []
        for py in sorted((_REPO_ROOT / "harness").rglob("*.py")):
            for line in _home_dir_offenders(py.read_text()):
                offenders.append(f"{py.relative_to(_REPO_ROOT)}:{line}")
        assert not offenders, (
            "harness/ must be Path.home()-free (clone portability):\n"
            + "\n".join(offenders)
        )

    def test_guard_catches_real_code(self) -> None:
        """The real guard is intact: executable $HOME coupling is flagged."""
        for snippet in (
            "from pathlib import Path\nx = Path.home()\n",
            "import os\ny = os.path.expanduser('~/x')\n",
            "import os\nz = os.environ['HOME']\n",
            "import os\nw = os.environ.get('HOME')\n",
            "from pathlib import Path\nq = Path('~/cache')\n",
        ):
            assert _home_dir_offenders(snippet), f"guard missed: {snippet!r}"

    def test_guard_ignores_prose(self) -> None:
        """Docstrings / comments / strings mentioning the tokens do NOT trip it
        (the #33 deps.py docstring regression)."""
        prose = (
            '"""This module never calls Path.home() or reads $HOME.\n\n'
            "    It avoids os.path.expanduser and os.environ['HOME'].\n"
            '    """\n'
            "# also not Path.home() in a comment\n"
            "MSG = \"do not use Path.home() or os.environ['HOME']\"\n"
            "def f():\n"
            "    return 1\n"
        )
        assert _home_dir_offenders(prose) == []


# -- (3) bootstrap seeds a deny-all allowlist --------------------------------


class TestBootstrapDenyAllAllowlist:
    def _run_bootstrap(self, proj: Path) -> subprocess.CompletedProcess:
        (proj / "scripts").mkdir(parents=True)
        (proj / ".claude").mkdir(parents=True)
        (proj / ".gemini").mkdir(parents=True)
        (proj / "config").mkdir(parents=True)
        shutil.copy(
            _REPO_ROOT / "scripts" / "bootstrap.sh",
            proj / "scripts" / "bootstrap.sh",
        )
        (proj / "scripts" / "bootstrap.sh").chmod(0o755)
        for rel in (
            ".claude/settings.local.json.template",
            ".gemini/settings.json.template",
            "config/impl_preserve.template.md",
        ):
            src = _REPO_ROOT / rel
            if src.exists():
                shutil.copy(src, proj / rel)
        # HOME is redirected so the memory-seed step never touches the operator.
        return subprocess.run(
            ["bash", str(proj / "scripts" / "bootstrap.sh")],
            env={
                "CLAUDE_PROJECT_DIR": str(proj),
                "HOME": str(proj / "_home"),
                "PATH": "/usr/bin:/bin",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_bootstrap_seeds_comment_only_allowlist(self, tmp_path) -> None:
        proj = tmp_path / "proj"
        result = self._run_bootstrap(proj)
        assert result.returncode == 0, result.stderr
        allow = proj / "state" / "control" / "autowork" / "auto_promote.allowlist"
        assert allow.is_file(), "bootstrap did not seed the allowlist"
        # Deny-all == every non-empty line is a comment.
        for line in allow.read_text().splitlines():
            s = line.strip()
            if s:
                assert s.startswith("#"), (
                    f"allowlist must be deny-all (comment-only); got: {line!r}"
                )


# -- (4) _build_agent_env sets CLAUDE_PROJECT_DIR (drives REPL-8) -------------


class TestBuildAgentEnvSetsProjectDir:
    def test_build_agent_env_exports_claude_project_dir(self) -> None:
        # Until the env dict in _build_agent_env carries CLAUDE_PROJECT_DIR, a
        # fresh clone's spawned claude CLI cannot resolve ${CLAUDE_PROJECT_DIR}
        # in config/claude_mcp.json and config/claude_worker.json.
        from harness import orchestrator

        env = orchestrator._build_agent_env("claude", "state", 1)
        assert "CLAUDE_PROJECT_DIR" in env, (
            "_build_agent_env must set CLAUDE_PROJECT_DIR so a bare clone's "
            "${CLAUDE_PROJECT_DIR} placeholders resolve (REPL-8)"
        )
        assert env["CLAUDE_PROJECT_DIR"], "CLAUDE_PROJECT_DIR must be non-empty"
        assert env["CLAUDE_PROJECT_DIR"] == str(orchestrator.PROJECT_DIR), (
            "CLAUDE_PROJECT_DIR should point at the resolved project root"
        )

    def test_build_agent_env_trusts_gemini_workspace(self) -> None:
        # REPL-11: a fresh clone at /tmp/... is an untrusted directory for the
        # Gemini CLI, which then exits without submitting (code 55) and the
        # dual-agent dispatch fails. _build_agent_env must export
        # GEMINI_CLI_TRUST_WORKSPACE=true so the spawned gemini trusts any clone.
        from harness import orchestrator

        env = orchestrator._build_agent_env("gemini", "state", 1)
        assert env.get("GEMINI_CLI_TRUST_WORKSPACE") == "true", (
            "_build_agent_env must export GEMINI_CLI_TRUST_WORKSPACE=true so a "
            "fresh clone's gemini agent is not blocked by folder-trust (REPL-11)"
        )
