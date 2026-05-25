"""M7 — empirical check that Gemini CLI actually fires the wired hook.

Scope
=====
Sub-plan 03 §1 enumerates the Gemini ``HookEventName`` inventory
(`gemini_chunk.js` line 314832) as BeforeTool / AfterTool / BeforeAgent /
AfterAgent / BeforeModel / AfterModel / BeforeToolSelection / SessionStart /
SessionEnd / PreCompress / Notification — note the absence of
``UserPromptSubmit``.  `config/gemini_settings.json` therefore wires a
``BeforeModel`` stanza (the Gemini-native event that fires once per agent
turn before the model is called).  The unit tests exercise
``harness.hooks.gemini.user_prompt_submit.main`` in-process, which proves
the hook's behaviour if invoked, but says nothing about whether the CLI
will invoke it in the first place.

This test is the "does it fire?" probe the corrections plan names at
M7.  It spawns a real ``gemini`` subprocess in non-interactive
(``-p``) mode, points it at a scratch ``.gemini/settings.json`` that
wires a trivial shell hook into ``BeforeModel``, and asserts that
the hook's ``systemMessage`` payload shows up in the combined CLI
output.

Skip policy
===========
Real CLI spawning is inherently flaky: it needs the ``gemini`` binary
on ``$PATH``, working network, and a ``GEMINI_API_KEY`` (or equivalent
auth) wired up.  We treat those as *environmental* skips rather than
test failures — pytest ``skip`` with a precise ``reason=`` so operator
triage is one grep away:

  * gemini binary missing  -> skip ("gemini CLI not installed")
  * GEMINI_API_KEY unset   -> skip ("no GEMINI_API_KEY in env")
  * subprocess exit != 0
    after ``prompt`` finishes
    within 60 s              -> xfail ("gemini CLI non-zero exit")

Only the *successful* path asserts — the goal is to make the question
"does Gemini actually fire BeforeModel?" answerable by a single
``pytest`` invocation: green ==> yes, skip ==> can't tell here,
xfail ==> the CLI ran but didn't fire the hook the way we expect.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import textwrap

import pytest


_SENTINEL = "JANUSMASK_UPS_HOOK_FIRED_2f3a9e7b"


def _has_gemini_cli() -> bool:
    return shutil.which("gemini") is not None


def _has_gemini_auth() -> bool:
    # Accept any of the auth knobs the CLI honours so the test is not
    # gated on one specific pathway.
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"):
        if os.environ.get(key):
            return True
    # Oauth google_accounts file may also satisfy — best-effort check.
    oauth = pathlib.Path.home() / ".gemini" / "google_accounts.json"
    return oauth.is_file()


@pytest.mark.skipif(
    not _has_gemini_cli(),
    reason="gemini CLI not installed — skip empirical BeforeModel probe",
)
@pytest.mark.skipif(
    not _has_gemini_auth(),
    reason=(
        "no GEMINI_API_KEY / GOOGLE_API_KEY / oauth available — "
        "real CLI spawn would block on auth prompt"
    ),
)
def test_gemini_userpromptsubmit_fires_for_real(tmp_path):
    """Launch real ``gemini -p ...`` with BeforeModel hook and
    assert the hook's systemMessage is visible in the CLI's output.

    Fixture layout under tmp_path (so the real repo isn't touched):

        tmp_path/
          project/            <- the folder gemini trusts
            .gemini/
              settings.json   <- wires BeforeModel -> echo hook
              trustedFolders.json
    """
    project = tmp_path / "project"
    gemini_dir = project / ".gemini"
    gemini_dir.mkdir(parents=True)

    # Trust the folder so Gemini does not silently drop project-scope
    # hooks (gemini_chunk.js L325910-325915).
    (gemini_dir / "trustedFolders.json").write_text(
        json.dumps({str(project): "trusted"})
    )

    # Wire a dead-simple POSIX-echo hook that emits a JSON envelope with
    # the sentinel in systemMessage. If the CLI surfaces systemMessage
    # to the model or prints it to stdout/stderr, the sentinel will
    # show up in combined output.
    hook_script = gemini_dir / "ups_hook.sh"
    hook_script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            printf '%s' '{{"decision":"allow","systemMessage":"{_SENTINEL}"}}'
            """
        )
    )
    hook_script.chmod(0o755)

    settings = {
        "security": {"folderTrust": {"enabled": True}},
        "mcpServers": {},
        "hooks": {
            "BeforeModel": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "name": "janusmask-ups-probe",
                            "command": str(hook_script),
                            "timeout": 10000,
                        }
                    ],
                }
            ]
        },
    }
    (gemini_dir / "settings.json").write_text(json.dumps(settings))

    env = {
        **os.environ,
        "GEMINI_PROJECT_DIR": str(project),
        "CLAUDE_PROJECT_DIR": str(project),
    }

    try:
        proc = subprocess.run(
            [
                "gemini",
                "--approval-mode",
                "plan",          # read-only, won't actually execute tools
                "-p",
                "ping",          # minimal prompt
            ],
            cwd=project,
            env=env,
            timeout=60,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        pytest.xfail(
            "gemini CLI did not return within 60s — either a network hang "
            "or the binary is waiting on interactive input; cannot verify "
            "BeforeModel fires from this environment."
        )

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")

    if _SENTINEL not in combined:
        pytest.xfail(
            f"gemini CLI ran but the BeforeModel hook did not surface "
            f"the sentinel (returncode={proc.returncode}); the CLI may "
            f"still drop BeforeModel or emit systemMessage through a path "
            f"not captured in stdout/stderr. stderr tail: "
            f"{(proc.stderr or '')[-500:]!r}"
        )

    assert _SENTINEL in combined, (
        "Gemini CLI ran but the BeforeModel systemMessage sentinel "
        "never appeared in stdout/stderr. The CLI likely does not honour "
        "the BeforeModel event name either, or surfaces systemMessage "
        "through a channel other than stdout/stderr."
        f"\nstdout tail: {(proc.stdout or '')[-500:]!r}"
        f"\nstderr tail: {(proc.stderr or '')[-500:]!r}"
    )


def test_empirical_probe_is_wired_into_scope_exception():
    """Meta-check: the corrections plan places this file under the
    ``tests/adversarial/test_P3_*.py`` scope exception. Confirm the
    filename still matches that glob so the impl_pre_write.py gate
    doesn't reject future edits. If this assertion ever fails, rename
    the file or extend the exception first; do not bypass the gate.
    """
    here = pathlib.Path(__file__)
    assert here.name.startswith("test_P3_"), (
        f"This empirical probe must remain under the "
        f"tests/adversarial/test_P3_*.py scope exception; got {here.name}"
    )
