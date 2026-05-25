"""Adversarial tests for harness.orchestrator._build_agent_command permission-mode injection.

Context
-------
B3 Path B originally landed at HEAD 6ec6e29 with a ``mode == 'synthesis'``
guard. The 2026-05-01 outbox-fallback work (commit 6043333) DROPPED that
guard because ``claude -p`` silently drops ``--settings`` in planning mode
too — injection must be unconditional for any claude spawn so the worker
can write ``outbox/submission.py``. Current shape in
``harness/orchestrator.py::_build_agent_command`` (line 149):

    raw_args = [rewire.get(a, a) for a in raw_args]
    if agent == 'claude' and '--permission-mode' not in raw_args:
        raw_args = raw_args + ['--permission-mode', 'acceptEdits']

Why: claude-code >=2.1.114 silently drops hook-granted permission verbs
under headless ``-p`` invocation. Injecting ``--permission-mode acceptEdits``
bypasses the default-deny on Write. ``mode`` (from
``os.environ['JANUSMASK_MODE']``, default ``'synthesis'``) still drives
the hook-config rewire table but no longer gates injection.

Vector coverage (15 vectors — see brief):
 1  synthesis + claude + fresh config      -> test_v01_synthesis_claude_appends_flag
 2  operator override ``plan``              -> test_v02_existing_permission_mode_plan_not_duplicated
 3  operator override ``bypassPermissions`` -> test_v03_existing_permission_mode_bypass_not_overridden
 4  JANUSMASK_MODE=planning                 -> test_v04_planning_mode_still_injects_post_b3_lift
 5  synthesis + gemini                      -> test_v05_synthesis_gemini_no_injection
 6  planning + gemini                       -> test_v06_planning_gemini_no_injection
 7  mode env unset -> default synthesis     -> test_v07_mode_env_unset_defaults_synthesis
 8  JANUSMASK_MODE=''                       -> test_v08_empty_mode_still_injects_post_b3_lift
 9  prompt still after -p after injection   -> test_v09_prompt_position_preserved
10  raw_args lacks -p entirely              -> test_v10_no_dash_p_appends_prompt_last
11  agent='CLAUDE' case-sensitivity         -> test_v11_uppercase_agent_no_injection
12  rewire table interaction                -> test_v12_rewire_then_inject
13  idempotency (no mutation of config)     -> test_v13_config_list_not_mutated
14  mode interleave via monkeypatch         -> test_v14_mode_interleave
15  full config.yaml-shaped claude args     -> test_v15_full_realistic_config

Hermetic: no subprocess, no fs mutation, no network. ``monkeypatch.setenv``
for mode control; ``copy.deepcopy`` to prove no mutation of caller's dict.
Filed under ``tests/adversarial/`` per META allow-list. No production edits.
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from harness.orchestrator import _build_agent_command  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CLAUDE_WORKER_JSON = f"{_PROJECT_ROOT}/config/claude_worker.json"
CLAUDE_WORKER_HOOKS_JSON = f"{_PROJECT_ROOT}/config/claude_worker_hooks.json"
CLAUDE_WORKER_PLANNING_HOOKS_JSON = (
    f"{_PROJECT_ROOT}/config/claude_worker_planning_hooks.json"
)
GEMINI_POLICY_TOML = f"{_PROJECT_ROOT}/config/gemini_worker_policy.toml"
GEMINI_POLICY_PLANNING_TOML = (
    f"{_PROJECT_ROOT}/config/gemini_worker_policy_planning.toml"
)
CLAUDE_MCP_JSON = f"{_PROJECT_ROOT}/config/claude_mcp.json"


def _minimal_claude_config() -> dict:
    """Tiny claude config — -p + single settings path, so rewire is observable."""
    return {
        'agents': {
            'claude': {
                'command': 'claude',
                'args': [
                    '-p',
                    '--settings',
                    CLAUDE_WORKER_JSON,
                ],
            },
            'gemini': {
                'command': 'gemini',
                'args': [
                    '-p',
                    '--admin-policy',
                    GEMINI_POLICY_TOML,
                ],
            },
        }
    }


def _realistic_claude_config() -> dict:
    """Mirrors harness/config.yaml agents.claude.args verbatim as of HEAD 6ec6e29."""
    return {
        'agents': {
            'claude': {
                'command': 'claude',
                'args': [
                    '-p',
                    '--model',
                    'haiku',
                    '--output-format',
                    'stream-json',
                    '--include-partial-messages',
                    '--settings',
                    CLAUDE_WORKER_JSON,
                    '--mcp-config',
                    CLAUDE_MCP_JSON,
                    '--strict-mcp-config',
                    '--setting-sources',
                    '',
                ],
            },
            'gemini': {
                'command': 'gemini',
                'args': [
                    '-p',
                    '-o',
                    'stream-json',
                    '--admin-policy',
                    GEMINI_POLICY_TOML,
                    '--allowed-mcp-server-names',
                    'janusmask',
                    '--approval-mode',
                    'yolo',
                ],
            },
        }
    }


@pytest.fixture
def synthesis_env(monkeypatch):
    monkeypatch.setenv('JANUSMASK_MODE', 'synthesis')
    return 'synthesis'


@pytest.fixture
def planning_env(monkeypatch):
    monkeypatch.setenv('JANUSMASK_MODE', 'planning')
    return 'planning'


# ---------------------------------------------------------------------------
# Vector 1: synthesis mode + claude + no existing --permission-mode → appended.
# ---------------------------------------------------------------------------
def test_v01_synthesis_claude_appends_flag(synthesis_env):
    cfg = _minimal_claude_config()
    cmd = _build_agent_command('claude', 'hello', cfg)

    # command must begin with the binary
    assert cmd[0] == 'claude'
    # injection present
    assert '--permission-mode' in cmd
    idx = cmd.index('--permission-mode')
    assert cmd[idx + 1] == 'acceptEdits'
    # exactly one pair injected
    assert cmd.count('--permission-mode') == 1
    assert cmd.count('acceptEdits') == 1


# ---------------------------------------------------------------------------
# Vector 2: operator override with --permission-mode plan is preserved.
# ---------------------------------------------------------------------------
def test_v02_existing_permission_mode_plan_not_duplicated(synthesis_env):
    cfg = _minimal_claude_config()
    cfg['agents']['claude']['args'] += ['--permission-mode', 'plan']
    cmd = _build_agent_command('claude', 'hi', cfg)

    # only one --permission-mode in the final cmd — the operator's
    assert cmd.count('--permission-mode') == 1
    idx = cmd.index('--permission-mode')
    assert cmd[idx + 1] == 'plan'
    # acceptEdits must NOT have been appended
    assert 'acceptEdits' not in cmd


# ---------------------------------------------------------------------------
# Vector 3: operator override with bypassPermissions is preserved.
# ---------------------------------------------------------------------------
def test_v03_existing_permission_mode_bypass_not_overridden(synthesis_env):
    cfg = _minimal_claude_config()
    cfg['agents']['claude']['args'] += ['--permission-mode', 'bypassPermissions']
    cmd = _build_agent_command('claude', 'hi', cfg)

    assert cmd.count('--permission-mode') == 1
    idx = cmd.index('--permission-mode')
    assert cmd[idx + 1] == 'bypassPermissions'
    assert 'acceptEdits' not in cmd


# ---------------------------------------------------------------------------
# Vector 4: JANUSMASK_MODE=planning → injection STILL fires for claude
# (post-2026-05-01 6043333 B3-guard lift; claude -p drops --settings in
# planning mode too, so the Write default-deny must be bypassed).
# ---------------------------------------------------------------------------
def test_v04_planning_mode_still_injects_post_b3_lift(planning_env):
    cfg = _minimal_claude_config()
    # re-point to the planning rewire source so the list still contains
    # something that would be rewired; verifies rewire table used AND
    # injection still triggers (unconditional for claude).
    cmd = _build_agent_command('claude', 'hi', cfg)
    assert '--permission-mode' in cmd
    idx = cmd.index('--permission-mode')
    assert cmd[idx + 1] == 'acceptEdits'
    assert cmd.count('--permission-mode') == 1
    # planning rewire kicked in
    assert CLAUDE_WORKER_PLANNING_HOOKS_JSON in cmd
    assert CLAUDE_WORKER_JSON not in cmd


# ---------------------------------------------------------------------------
# Vector 5: synthesis mode + gemini → no injection.
# ---------------------------------------------------------------------------
def test_v05_synthesis_gemini_no_injection(synthesis_env):
    cfg = _minimal_claude_config()
    cmd = _build_agent_command('gemini', 'hi', cfg)
    assert '--permission-mode' not in cmd
    assert 'acceptEdits' not in cmd


# ---------------------------------------------------------------------------
# Vector 6: planning + gemini → no injection.
# ---------------------------------------------------------------------------
def test_v06_planning_gemini_no_injection(planning_env):
    cfg = _minimal_claude_config()
    cmd = _build_agent_command('gemini', 'hi', cfg)
    assert '--permission-mode' not in cmd
    assert 'acceptEdits' not in cmd
    # planning rewire for gemini policy path
    assert GEMINI_POLICY_PLANNING_TOML in cmd
    assert GEMINI_POLICY_TOML not in cmd


# ---------------------------------------------------------------------------
# Vector 7: mode env var unset → defaults to 'synthesis' → inject for claude.
# ---------------------------------------------------------------------------
def test_v07_mode_env_unset_defaults_synthesis(monkeypatch):
    monkeypatch.delenv('JANUSMASK_MODE', raising=False)
    cfg = _minimal_claude_config()
    cmd = _build_agent_command('claude', 'hi', cfg)
    assert '--permission-mode' in cmd
    idx = cmd.index('--permission-mode')
    assert cmd[idx + 1] == 'acceptEdits'
    # synthesis rewire applied
    assert CLAUDE_WORKER_HOOKS_JSON in cmd
    assert CLAUDE_WORKER_JSON not in cmd


# ---------------------------------------------------------------------------
# Vector 8: JANUSMASK_MODE='' → '' != 'synthesis' for rewire purposes,
# but injection is unconditional for claude post-2026-05-01 lift.
# ---------------------------------------------------------------------------
def test_v08_empty_mode_still_injects_post_b3_lift(monkeypatch):
    monkeypatch.setenv('JANUSMASK_MODE', '')
    cfg = _minimal_claude_config()
    cmd = _build_agent_command('claude', 'hi', cfg)
    # empty string is not 'synthesis' → falls to planning rewire table,
    # but injection still fires (no mode gate on the injection branch).
    assert '--permission-mode' in cmd
    idx = cmd.index('--permission-mode')
    assert cmd[idx + 1] == 'acceptEdits'
    # planning rewire triggered (the else-branch of the ternary)
    assert CLAUDE_WORKER_PLANNING_HOOKS_JSON in cmd


# ---------------------------------------------------------------------------
# Vector 9: -p stays at position 1 and <prompt> stays at position 2 after
# injection (new flags get appended, not inserted ahead of -p).
# ---------------------------------------------------------------------------
def test_v09_prompt_position_preserved(synthesis_env):
    cfg = _minimal_claude_config()
    cmd = _build_agent_command('claude', 'THE_PROMPT', cfg)

    # command[0] = 'claude', command[1] = '-p', command[2] = 'THE_PROMPT'
    assert cmd[0] == 'claude'
    assert cmd[1] == '-p'
    assert cmd[2] == 'THE_PROMPT'

    # and the injected pair is after the prompt, somewhere in the tail
    tail = cmd[3:]
    assert '--permission-mode' in tail
    assert tail[tail.index('--permission-mode') + 1] == 'acceptEdits'


# ---------------------------------------------------------------------------
# Vector 10: raw_args lacks -p entirely → acceptEdits appended, then
# -p <prompt> appended last via the ValueError fallback.
# ---------------------------------------------------------------------------
def test_v10_no_dash_p_appends_prompt_last(synthesis_env):
    cfg = {
        'agents': {
            'claude': {
                'command': 'claude',
                'args': ['--model', 'haiku'],  # no -p in config
            }
        }
    }
    cmd = _build_agent_command('claude', 'PROMPT_X', cfg)

    # prompt is the very last element, preceded by -p
    assert cmd[-2] == '-p'
    assert cmd[-1] == 'PROMPT_X'
    # injection is before the trailing -p PROMPT_X
    assert '--permission-mode' in cmd[:-2]
    idx = cmd.index('--permission-mode')
    assert cmd[idx + 1] == 'acceptEdits'


# ---------------------------------------------------------------------------
# Vector 11: agent='CLAUDE' (uppercase) does NOT trigger injection.
# Documents the current sharp edge: the guard is case-sensitive.
# ---------------------------------------------------------------------------
def test_v11_uppercase_agent_no_injection(synthesis_env):
    cfg = {
        'agents': {
            'CLAUDE': {  # non-standard capitalisation
                'command': 'claude',
                'args': ['-p', '--model', 'haiku'],
            }
        }
    }
    cmd = _build_agent_command('CLAUDE', 'hi', cfg)
    # no injection despite synthesis + "claude-like" agent key
    assert '--permission-mode' not in cmd
    assert 'acceptEdits' not in cmd


# ---------------------------------------------------------------------------
# Vector 12: rewire table replaces claude_worker.json with claude_worker_hooks.json,
# THEN injection still happens on the rewired list.
# ---------------------------------------------------------------------------
def test_v12_rewire_then_inject(synthesis_env):
    cfg = _minimal_claude_config()
    cmd = _build_agent_command('claude', 'hi', cfg)

    assert CLAUDE_WORKER_HOOKS_JSON in cmd
    assert CLAUDE_WORKER_JSON not in cmd
    # and injection still landed after rewire
    assert '--permission-mode' in cmd
    assert cmd[cmd.index('--permission-mode') + 1] == 'acceptEdits'
    # rewired path precedes the injected flag (flag is appended to end)
    assert cmd.index(CLAUDE_WORKER_HOOKS_JSON) < cmd.index('--permission-mode')


# ---------------------------------------------------------------------------
# Vector 13: idempotency — calling _build_agent_command twice with the same
# config + prompt does not mutate config['agents']['claude']['args'] and
# returns equal cmd lists.
# ---------------------------------------------------------------------------
def test_v13_config_list_not_mutated(synthesis_env):
    cfg = _minimal_claude_config()
    original_args = copy.deepcopy(cfg['agents']['claude']['args'])

    cmd1 = _build_agent_command('claude', 'hi', cfg)
    # config unchanged
    assert cfg['agents']['claude']['args'] == original_args
    assert CLAUDE_WORKER_JSON in cfg['agents']['claude']['args']
    assert '--permission-mode' not in cfg['agents']['claude']['args']

    cmd2 = _build_agent_command('claude', 'hi', cfg)
    # second call config still unchanged
    assert cfg['agents']['claude']['args'] == original_args
    # outputs are equal
    assert cmd1 == cmd2


# ---------------------------------------------------------------------------
# Vector 14: interleaved mode changes via monkeypatch produce distinct cmds.
# ---------------------------------------------------------------------------
def test_v14_mode_interleave(monkeypatch):
    cfg = _minimal_claude_config()

    monkeypatch.setenv('JANUSMASK_MODE', 'synthesis')
    cmd_syn = _build_agent_command('claude', 'hi', cfg)

    monkeypatch.setenv('JANUSMASK_MODE', 'planning')
    cmd_plan = _build_agent_command('claude', 'hi', cfg)

    monkeypatch.setenv('JANUSMASK_MODE', 'synthesis')
    cmd_syn2 = _build_agent_command('claude', 'hi', cfg)

    # synthesis cmds match across the gap
    assert cmd_syn == cmd_syn2
    # synthesis vs planning differ (rewire target differs)
    assert cmd_syn != cmd_plan
    # both modes inject for claude (post-2026-05-01 6043333 lift) — the
    # difference is the rewire target, not the injection.
    assert '--permission-mode' in cmd_syn
    assert '--permission-mode' in cmd_plan
    assert cmd_syn[cmd_syn.index('--permission-mode') + 1] == 'acceptEdits'
    assert cmd_plan[cmd_plan.index('--permission-mode') + 1] == 'acceptEdits'
    # rewire targets differ
    assert CLAUDE_WORKER_HOOKS_JSON in cmd_syn
    assert CLAUDE_WORKER_PLANNING_HOOKS_JSON in cmd_plan


# ---------------------------------------------------------------------------
# Vector 15: full realistic config (copied from harness/config.yaml) →
# injection lands cleanly alongside --settings, --mcp-config,
# --strict-mcp-config, and --setting-sources "".
# ---------------------------------------------------------------------------
def test_v15_full_realistic_config(synthesis_env):
    cfg = _realistic_claude_config()
    cmd = _build_agent_command('claude', 'PROMPT', cfg)

    # every config.yaml arg is still present
    for expected in [
        '--model', 'haiku',
        '--output-format', 'stream-json',
        '--include-partial-messages',
        '--settings', CLAUDE_WORKER_HOOKS_JSON,  # rewired
        '--mcp-config', CLAUDE_MCP_JSON,
        '--strict-mcp-config',
        '--setting-sources', '',
    ]:
        assert expected in cmd, f'missing {expected!r} in {cmd!r}'

    # original pre-rewire path must be gone
    assert CLAUDE_WORKER_JSON not in cmd

    # injection present and exactly once
    assert cmd.count('--permission-mode') == 1
    assert cmd[cmd.index('--permission-mode') + 1] == 'acceptEdits'

    # prompt is correctly slotted immediately after -p
    assert cmd[0] == 'claude'
    assert cmd[1] == '-p'
    assert cmd[2] == 'PROMPT'

    # --strict-mcp-config is a bare switch; confirm it's not consumed
    # as a value of --setting-sources (which is followed by "")
    ss_idx = cmd.index('--setting-sources')
    assert cmd[ss_idx + 1] == ''
