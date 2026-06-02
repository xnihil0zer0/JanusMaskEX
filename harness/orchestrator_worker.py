"""Single-shot orchestrator worker for the autowork daemon (AW2).

Spawned per-task by the autowork daemon: claims ONE task_id, runs the
synthesis -> AST -> fuzz -> cross-exam -> auto-commit pipeline once, then
exits.

Reuses module-level helpers from ``harness.orchestrator`` (claim path,
validation, repair, save/commit, fuzz persistence, lifecycle ledger) so
the existing serial ``run_pipeline`` remains byte-identical and the
worker cannot bypass any validator. Mirrors ``get_next_task``'s atomic
rename idiom -- ``candidate.rename(candidate.with_suffix('.json.processing'))``
inside a ``try/except FileNotFoundError`` -- so a peer worker that has
already claimed the task simply causes this process to exit 0 with
``{"skipped": "already_claimed"}``.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
DEFAULT_CONFIG_PATH = Path('harness/config.yaml')

def _emit_lifecycle_safe(state_dir: Path, **fields: Any) -> None:
    """Best-effort ledger append; mirrors orchestrator._emit_lifecycle.

    Kept local so the not_found / already_claimed exit paths do not pull
    the full ``harness.orchestrator`` module (which transitively imports
    yaml, the diff fuzzer, etc.). Once the claim succeeds we delegate to
    the canonical helper via ``orch._emit_lifecycle``.
    """
    try:
        from harness._journal import write_jsonl_row
        row = {'ts': time.time(), **fields}
        write_jsonl_row(state_dir / 'impl_progress.jsonl', row)
    except Exception:
        pass

def _print_json_line(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + '\n')
    sys.stdout.flush()

def _consume_no_diff_marker(state_dir: Path, task_id: str) -> bool:
    """True if _auto_commit_accepted wrote a no_diff marker (G-NODIFF).

    A no_diff outcome means the brief is already satisfied (the agents produced
    no change) -- it is genuinely DONE, not a failure. Routing it to processed/
    instead of blocked/ stops the daemon burning its 3-attempt retry budget on a
    deterministic no-op. Best-effort; never raises."""
    marker = state_dir / 'output' / f'{task_id}.no_diff'
    try:
        if marker.exists():
            marker.unlink()
            return True
    except OSError:
        pass
    return False

def _rollback_live_tree(state_dir: Path, files_touched: list[Any], task_id: str) -> None:
    """CONTAIN C3: restore the live worktree on any non-accept worker outcome.

    AGENT-ISOLATION: an agent subprocess can write the live repo by absolute
    path -- CWD relocation is NOT a filesystem jail (harness/paths.py:33-36).
    On an ACCEPTED run the validated submission is applied through the
    ``<repo>_staging`` worktree and ff-merged, overwriting any stray write; but
    on a REJECT / timeout / decompose outcome the accept path is never reached,
    so a stray edit to a ``files_touched`` target would PERSIST (the proximate
    cause of the GAP_H4 tamper that survived rejection). Mirror the staging-commit
    scrub (``orchestrator._auto_commit_accepted``) in the LIVE worktree:
    best-effort ``git checkout HEAD -- <rel>`` + ``git clean -f -- <rel>``, scoped
    STRICTLY to the resolved targets (R-CONTAIN-3) so the committed oracle and
    unrelated working-tree drift are never touched. Never raises.

    ``files_touched`` on a reject path holds only the original declared targets:
    ``_detect_and_append_untracked_tests`` (which appends untracked tests) runs
    only on accept paths, so this can never delete an operator's untracked WIP.
    """
    import subprocess
    rels = [r for r in (files_touched or []) if isinstance(r, str) and r.strip()]
    if not rels:
        return
    # Resolve the live worktree STRICTLY from state_dir's git toplevel. In
    # production state_dir is always <repo>/state; if it does not resolve to a
    # repo there is no live tree to restore, so skip rather than fall back to a
    # global root (which could touch an unrelated checkout under test).
    try:
        top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=str(state_dir),
                             capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return
    if top.returncode != 0 or not top.stdout.strip():
        return
    repo_root = top.stdout.strip()
    for rel in rels:
        try:
            subprocess.run(['git', 'checkout', 'HEAD', '--', rel], cwd=repo_root,
                           check=False, timeout=30, capture_output=True)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        try:
            subprocess.run(['git', 'clean', '-f', '--', rel], cwd=repo_root,
                           check=False, timeout=30, capture_output=True)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    _emit_lifecycle_safe(state_dir, phase='autowork', task_id=task_id,
                         event='reject_rollback', files=rels)



def main() -> int:
    parser = argparse.ArgumentParser(description='JanusMask single-task orchestrator worker (AW2).')
    parser.add_argument('--state-dir', type=Path, required=True, help='Path to the shared state directory.')
    parser.add_argument('--task-id', type=str, required=True, help='Task identifier whose JSON lives in <state>/tasks/.')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG_PATH, help='Path to harness/config.yaml.')
    args = parser.parse_args()
    state_dir: Path = args.state_dir.resolve()
    task_id: str = args.task_id
    config_path: Path = args.config
    tasks_dir = state_dir / 'tasks'
    candidate = tasks_dir / f'{task_id}.json'
    processing = candidate.with_suffix('.json.processing')
    if not candidate.exists():
        _print_json_line({'skipped': 'not_found', 'task_id': task_id})
        return 0
    try:
        candidate.rename(processing)
    except FileNotFoundError:
        _print_json_line({'skipped': 'already_claimed', 'task_id': task_id})
        return 0
    exit_code = 2
    task: dict[str, Any] = {}
    started_emit = False
    _stderr_buf = io.StringIO()
    with contextlib.redirect_stderr(_stderr_buf):
        try:
            worker_start_monotonic = time.monotonic()
            _emit_lifecycle_safe(state_dir, phase='autowork', task_id=task_id, event='worker_start')
            started_emit = True
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from harness import orchestrator as orch
            from harness.state import init_state, locked_read_modify_write, set_agent_status, set_phase
            from harness.planner.taxonomies import BYPASS_FUZZER_TYPES, SKIP_SMOKE_GATE_TYPES, META_TASK_POLICY
            from harness.sandbox_smoke import smoke_import
            from harness.embedded_test_runner import run_embedded_tests
            from harness.narrow_fuzz import run_narrow_fuzz
            from harness.diff_fuzzer import fuzz_from_task
            from harness.cross_examiner import prepare_exam_packets, write_feedback_files, clear_feedback_files
            from harness.task_decomposer import decompose_task, enqueue_subtasks, update_parent_state
            from harness.ast_retry import synthesize_with_retries
            config = orch.load_config(config_path)
            HARD_TIMEOUT_SECONDS, SYNTHESIS_WINDOW_SECONDS = _compute_timeout_budgets(config)
            config['state_dir'] = str(state_dir)
            state_dir.mkdir(parents=True, exist_ok=True)
            tasks_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / 'sessions').mkdir(parents=True, exist_ok=True)
            init_state(state_dir)
            orch._clear_stale_submissions(state_dir, task_id)
            with open(processing, 'r', encoding='utf-8') as fh:
                task = json.load(fh)
            current_task_path = current_task_spec_path(state_dir, task_id)
            try:
                current_task_path.write_text(json.dumps(task, indent=2))
            except OSError:
                pass
            os.environ['JANUSMASK_TASK_ID'] = task_id
            _precompute_baseline_test_results(state_dir, task, task_id)
            round_number = 1
            max_ast_retries = config['synthesis'].get('max_ast_retries', 3)
            use_retry_module = config['synthesis'].get('use_retry_module', False)
            active_agents = config.get('synthesis', {}).get('active_agents', ['claude', 'gemini'])
            agent_a = active_agents[0]
            agent_b = active_agents[1] if len(active_agents) > 1 else active_agents[0]
            synthesis_success = False
            agent_a_code: str | None = None
            agent_b_code: str | None = None
            base_prompt = orch.prepare_task_prompt(task)

            def _set_task_state(state: dict[str, Any]) -> dict[str, Any]:
                state['task_id'] = task_id
                state['round'] = round_number
                state['phase'] = 'synthesis'
                for agent_name in active_agents:
                    state[f'{agent_name}_status'] = 'running'
                state['status_updated_at_epoch'] = time.time()
                state['fuzz_results'] = None
                state['cross_exam_round'] = 0
                return state
            if use_retry_module:
                locked_read_modify_write(_set_task_state, state_dir)
                results: dict[str, tuple[bool, str | None]] = {}
                if config.get('synthesis', {}).get('antigravity_mode', True):
                    for agent_name in (agent_a, agent_b):
                        try:
                            ok, code, _violations = synthesize_with_retries(agent_name, base_prompt, config, state_dir, round_number, task, orch.run_agent_phase, (lambda a: lambda code, t: orch._validate_submission(code, a, t))(agent_name))
                        except Exception:
                            ok, code = (False, None)
                        results[agent_name] = (ok, code)
                else:
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        futures = {executor.submit(synthesize_with_retries, agent_name, base_prompt, config, state_dir, round_number, task, orch.run_agent_phase, (lambda a: lambda code, t: orch._validate_submission(code, a, t))(agent_name)): agent_name for agent_name in (agent_a, agent_b)}
                        for future in as_completed(futures):
                            agent_name = futures[future]
                            try:
                                ok, code, _violations = future.result()
                            except Exception:
                                ok, code = (False, None)
                            results[agent_name] = (ok, code)
                agent_a_ok, agent_a_code = results.get(agent_a, (False, None))
                agent_b_ok, agent_b_code = results.get(agent_b, (False, None))
                for agent_name, code in [(agent_a, agent_a_code), (agent_b, agent_b_code)]:
                    if code is None:
                        set_agent_status(state_dir, agent=agent_name, status='timeout')
                        orch._emit_lifecycle(state_dir, event='agent_status', agent=agent_name, status='timeout', task_id=task_id)
                    else:
                        set_agent_status(state_dir, agent=agent_name, status='submitted')
                        orch._emit_lifecycle(state_dir, event='agent_status', agent=agent_name, status='submitted', task_id=task_id)
                # GAP_H4: keep the RECONCILE_TIMEOUT_BUDGETS double-timeout protection
                # on the use_retry_module path too (parity with the non-retry branch's
                # `both agents timed out` guard). The per-call wall-budget guard now lives
                # inside synthesize_with_retries (ast_retry.py), so the budget-exhaustion
                # re-check the non-retry loop does at retry-start is already covered on
                # this path; the remaining gap was double-timeout handling. Both agents
                # produced no code => treat as timeout and exit 2 (the daemon retries a
                # timeout, vs a hard reject) instead of falling through to ast_validation.
                if agent_a_code is None and agent_b_code is None:
                    orch._emit_lifecycle(state_dir, event='double_timeout', task_id=task_id, detail='both agents timed out (retry_module); exiting before validation')
                    _print_json_line({'task_id': task_id, 'outcome': 'timeout', 'reason': 'both_agents_timed_out'})
                    exit_code = 2
                    return exit_code
                set_phase(state_dir, phase='ast_validation')
                orch._emit_lifecycle(state_dir, event='phase_transition', phase='ast_validation', task_id=task_id, phase_transition={'to': 'ast_validation'})
                synthesis_success = bool(agent_a_ok and agent_b_ok and agent_a_code and agent_b_code)
            else:
                ast_retries = 0
                agent_a_prompt = base_prompt
                agent_b_prompt = base_prompt
                while ast_retries < max_ast_retries:
                    if ast_retries > 0:
                        remaining_budget = HARD_TIMEOUT_SECONDS - (time.monotonic() - worker_start_monotonic)
                        if remaining_budget < SYNTHESIS_WINDOW_SECONDS:
                            orch._emit_lifecycle(state_dir, event='retry_budget_exhausted', task_id=task_id, detail=f'remaining {remaining_budget:.1f}s < synthesis window {SYNTHESIS_WINDOW_SECONDS:.0f}s')
                            _print_json_line({'task_id': task_id, 'outcome': 'timeout', 'reason': 'insufficient_time_for_retry', 'remaining_seconds': round(remaining_budget, 1)})
                            exit_code = 2
                            return exit_code
                    locked_read_modify_write(_set_task_state, state_dir)
                    agent_a_code, agent_b_code = orch.run_both_agents(agent_a_prompt, agent_b_prompt, config, state_dir, round_number, phase_name='synthesis')
                    for agent, code in [(agent_a, agent_a_code), (agent_b, agent_b_code)]:
                        if code is None:
                            set_agent_status(state_dir, agent=agent, status='timeout')
                            orch._emit_lifecycle(state_dir, event='agent_status', agent=agent, status='timeout', task_id=task_id)
                        else:
                            set_agent_status(state_dir, agent=agent, status='submitted')
                            orch._emit_lifecycle(state_dir, event='agent_status', agent=agent, status='submitted', task_id=task_id)
                    if agent_a_code is None and agent_b_code is None:
                        ast_retries += 1
                        orch._emit_lifecycle(state_dir, event='double_timeout', task_id=task_id, detail='both agents timed out; exiting before retry')
                        _print_json_line({'task_id': task_id, 'outcome': 'timeout', 'reason': 'both_agents_timed_out', 'attempt': ast_retries})
                        exit_code = 2
                        return exit_code
                    if not agent_a_code or not agent_b_code:
                        ast_retries += 1
                        if not agent_a_code:
                            agent_a_prompt = base_prompt + '\n\nError: Your previous submission timed out or was missing. Please try again.'
                        else:
                            agent_a_prompt = base_prompt
                        if not agent_b_code:
                            agent_b_prompt = base_prompt + '\n\nError: Your previous submission timed out or was missing. Please try again.'
                        else:
                            agent_b_prompt = base_prompt
                        continue
                    set_phase(state_dir, phase='ast_validation')
                    orch._emit_lifecycle(state_dir, event='phase_transition', phase='ast_validation', task_id=task_id, phase_transition={'to': 'ast_validation'})
                    agent_a_valid, agent_a_violations = orch._validate_submission(agent_a_code, agent_a, task)
                    agent_b_valid, agent_b_violations = orch._validate_submission(agent_b_code, agent_b, task)
                    if not agent_a_valid:
                        repaired = orch._try_auto_repair(agent_a_code, agent_a_violations, agent_a, task_id)
                        if repaired is not None:
                            revalid_ok, revalid_v = orch._validate_submission(repaired, agent_a, task)
                            if revalid_ok:
                                agent_a_code = repaired
                                agent_a_valid = True
                                agent_a_violations = revalid_v
                    if not agent_b_valid:
                        repaired = orch._try_auto_repair(agent_b_code, agent_b_violations, agent_b, task_id)
                        if repaired is not None:
                            revalid_ok, revalid_v = orch._validate_submission(repaired, agent_b, task)
                            if revalid_ok:
                                agent_b_code = repaired
                                agent_b_valid = True
                                agent_b_violations = revalid_v
                    if not (agent_a_valid and agent_b_valid):
                        ast_retries += 1
                        if not agent_a_valid:
                            error_msgs = '\n'.join((f'- {v.rule} (Line {v.line}): {v.message}' for v in agent_a_violations if v.severity == 'error'))
                            agent_a_prompt = base_prompt + f'\n\nYour previous submission failed AST validation:\n{error_msgs}\n\nPlease fix these errors and resubmit.'
                        else:
                            agent_a_prompt = base_prompt
                        if not agent_b_valid:
                            error_msgs = '\n'.join((f'- {v.rule} (Line {v.line}): {v.message}' for v in agent_b_violations if v.severity == 'error'))
                            agent_b_prompt = base_prompt + f'\n\nYour previous submission failed AST validation:\n{error_msgs}\n\nPlease fix these errors and resubmit.'
                        else:
                            agent_b_prompt = base_prompt
                        continue
                    synthesis_success = True
                    break
            if not synthesis_success:
                set_phase(state_dir, phase='rejected')
                orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                orch._mark_blocked(state_dir, task_id, 'synthesis_or_ast_failed')
                orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': 'synthesis_or_ast_failed'})
                exit_code = 1
                return exit_code
            mtt = task.get('meta_task_type') or task.get('constraints', {}).get('meta_task_type')
            _skip_ifz = (mtt == 'test_authoring') and META_TASK_POLICY.get('test_authoring', {}).get('skip_interface_fuzz')
            if mtt in BYPASS_FUZZER_TYPES or _skip_ifz:
                if mtt not in SKIP_SMOKE_GATE_TYPES and not _skip_ifz:
                    smoke_err = smoke_import('_smoke_candidate', agent_a_code)
                    if smoke_err is not None:
                        set_phase(state_dir, phase='rejected')
                        orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                        orch._mark_blocked(state_dir, task_id, 'smoke_failed')
                        orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                        _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': 'smoke_failed'})
                        exit_code = 1
                        return exit_code
                    # FLAG2_EMBEDDED_FUZZ (REV23 §C6): refuse to run the embedded-test
                    # runner UNJAILED on an EXTERNAL target while agent_sandbox is OFF.
                    # working_dir is read at the call site only and NEVER threaded into
                    # the runner (the candidate is a JM-synthesized string in a tempdir,
                    # repo_root stays PROJECT_ROOT). Self-builds have working_dir absent
                    # -> _target_is_self(None) == True -> gate INERT. Helpers imported
                    # lazily in-body (no new module-level import / top symbol); orch does
                    # not re-export them so they are imported directly here.
                    working_dir = task.get('working_dir')
                    from harness import agent_jail
                    from harness.paths import _target_is_self
                    if not _target_is_self(working_dir) and not agent_jail.sandbox_enabled(config):
                        raise RuntimeError('FLAG2_EMBEDDED_FUZZ (REV23 §C6): refusing to run embedded tests UNJAILED on an EXTERNAL target while agent_sandbox is disabled (working_dir=%r is outside the JanusMask tree). An external candidate MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                    embedded_err = run_embedded_tests('_embedded_candidate', agent_a_code)
                    if embedded_err is not None:
                        set_phase(state_dir, phase='rejected')
                        orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                        orch._mark_blocked(state_dir, task_id, 'embedded_tests_failed')
                        orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                        _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': 'embedded_tests_failed'})
                        exit_code = 1
                        return exit_code
                    # FLAG2_EMBEDDED_FUZZ (REV23 §C6): same fail-closed gate for the
                    # narrow-fuzz runner. On the external + sandbox-OFF path the embedded
                    # gate above fires first, so neither runner is ever reached; this
                    # guard keeps the narrow site refusal-complete in its own right.
                    working_dir = task.get('working_dir')
                    from harness import agent_jail
                    from harness.paths import _target_is_self
                    if not _target_is_self(working_dir) and not agent_jail.sandbox_enabled(config):
                        raise RuntimeError('FLAG2_EMBEDDED_FUZZ (REV23 §C6): refusing to run narrow-fuzz UNJAILED on an EXTERNAL target while agent_sandbox is disabled (working_dir=%r is outside the JanusMask tree). An external candidate MUST run inside the bubblewrap jail; enable agent_sandbox.bwrap or origin the task against self.' % (working_dir,))
                    narrow_err = run_narrow_fuzz(mtt, '_narrow_fuzz_candidate', agent_a_code)
                    if narrow_err is not None:
                        set_phase(state_dir, phase='rejected')
                        orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                        orch._mark_blocked(state_dir, task_id, 'narrow_fuzz_failed')
                        orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                        _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': 'narrow_fuzz_failed'})
                        exit_code = 1
                        return exit_code
                _detect_and_append_untracked_tests(state_dir, task, task_id, processing)
                orch._save_final_output(state_dir, task_id, agent_a_code)
                auto_commit_ok = orch._auto_commit_accepted(state_dir, task, task_id)
                no_diff = not auto_commit_ok and _consume_no_diff_marker(state_dir, task_id)
                if auto_commit_ok or no_diff:
                    orch._mark_processed(state_dir, task_id)
                else:
                    orch._mark_blocked(state_dir, task_id, 'auto_commit_failed')
                orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                if auto_commit_ok:
                    set_phase(state_dir, phase='accepted')
                    orch._emit_lifecycle(state_dir, event='phase_transition', phase='accepted', task_id=task_id, phase_transition={'to': 'accepted'})
                    _print_json_line({'task_id': task_id, 'outcome': 'accepted', 'path': 'bypass_fuzzer'})
                    exit_code = 0
                elif no_diff:
                    set_phase(state_dir, phase='accepted')
                    orch._emit_lifecycle(state_dir, event='phase_transition', phase='accepted', task_id=task_id, phase_transition={'to': 'accepted'})
                    _print_json_line({'task_id': task_id, 'outcome': 'no_diff', 'path': 'bypass_fuzzer'})
                    exit_code = 0
                else:
                    set_phase(state_dir, phase='rejected')
                    orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                    _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': 'auto_commit_failed'})
                    exit_code = 1
                return exit_code
            set_phase(state_dir, phase='fuzzing')
            orch._emit_lifecycle(state_dir, event='phase_transition', phase='fuzzing', task_id=task_id, phase_transition={'to': 'fuzzing'})
            fuzz_result = fuzz_from_task(agent_a_code, agent_b_code, task, config, session_id=f'{task_id}_r1')
            orch._persist_fuzz_results(state_dir, task_id, 'round1', fuzz_result)
            if fuzz_result.error:
                set_phase(state_dir, phase='rejected')
                orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                orch._mark_blocked(state_dir, task_id, 'fuzz_error_r1')
                orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': 'fuzz_error_r1'})
                exit_code = 1
                return exit_code
            if fuzz_result.equivalent:
                _detect_and_append_untracked_tests(state_dir, task, task_id, processing)
                orch._save_final_output(state_dir, task_id, agent_a_code)
                auto_commit_ok = orch._auto_commit_accepted(state_dir, task, task_id)
                no_diff = not auto_commit_ok and _consume_no_diff_marker(state_dir, task_id)
                if auto_commit_ok or no_diff:
                    orch._mark_processed(state_dir, task_id)
                else:
                    orch._mark_blocked(state_dir, task_id, 'auto_commit_failed_r1')
                orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                if auto_commit_ok:
                    set_phase(state_dir, phase='accepted')
                    orch._emit_lifecycle(state_dir, event='phase_transition', phase='accepted', task_id=task_id, phase_transition={'to': 'accepted'})
                    _print_json_line({'task_id': task_id, 'outcome': 'accepted', 'path': 'round1'})
                    exit_code = 0
                elif no_diff:
                    set_phase(state_dir, phase='accepted')
                    orch._emit_lifecycle(state_dir, event='phase_transition', phase='accepted', task_id=task_id, phase_transition={'to': 'accepted'})
                    _print_json_line({'task_id': task_id, 'outcome': 'no_diff', 'path': 'round1'})
                    exit_code = 0
                else:
                    set_phase(state_dir, phase='rejected')
                    orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                    _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': 'auto_commit_failed_r1'})
                    exit_code = 1
                return exit_code
            xexam_cfg = config.get('cross_examination', {}) if isinstance(config, dict) else {}
            try:
                max_rounds = int(xexam_cfg.get('max_rounds', 1))
            except (TypeError, ValueError):
                max_rounds = 1
            revised_agent_a = agent_a_code
            revised_agent_b = agent_b_code
            latest_failures = list(fuzz_result.failures)
            accumulated_failures = list(fuzz_result.failures)
            if max_rounds >= 1:
                task_spec = task.get('specification') or task.get('description') or ''
                for r in range(1, max_rounds + 1):
                    round_str = f'round{r + 1}'
                    set_phase(state_dir, phase='cross_examination')
                    orch._emit_lifecycle(state_dir, event='phase_transition', phase='cross_examination', task_id=task_id, phase_transition={'to': 'cross_examination'})
                    claude_packet, gemini_packet = prepare_exam_packets(revised_agent_a, revised_agent_b, task_spec, accumulated_failures)
                    write_feedback_files(state_dir, claude_packet, gemini_packet, r + 1)
                    r_agent_a, r_agent_b = orch.run_both_agents(claude_packet.review_prompt, gemini_packet.review_prompt, config, state_dir, r + 1, phase_name='cross_examination')
                    clear_feedback_files(state_dir)
                    revised_agent_a = r_agent_a or revised_agent_a
                    revised_agent_b = r_agent_b or revised_agent_b
                    set_phase(state_dir, phase='fuzzing')
                    orch._emit_lifecycle(state_dir, event='phase_transition', phase='fuzzing', task_id=task_id, phase_transition={'to': 'fuzzing'})
                    fuzz_result_n = fuzz_from_task(revised_agent_a, revised_agent_b, task, config, session_id=f'{task_id}_r{r + 1}')
                    orch._persist_fuzz_results(state_dir, task_id, round_str, fuzz_result_n)
                    if fuzz_result_n.error:
                        set_phase(state_dir, phase='rejected')
                        orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                        orch._mark_blocked(state_dir, task_id, f'fuzz_error_r{r + 1}')
                        orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                        _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': f'fuzz_error_r{r + 1}'})
                        exit_code = 1
                        return exit_code
                    if fuzz_result_n.equivalent:
                        _detect_and_append_untracked_tests(state_dir, task, task_id, processing)
                        orch._save_final_output(state_dir, task_id, revised_agent_a)
                        auto_commit_ok = orch._auto_commit_accepted(state_dir, task, task_id)
                        no_diff = not auto_commit_ok and _consume_no_diff_marker(state_dir, task_id)
                        if auto_commit_ok or no_diff:
                            orch._mark_processed(state_dir, task_id)
                        else:
                            orch._mark_blocked(state_dir, task_id, f'auto_commit_failed_r{r + 1}')
                        orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                        if auto_commit_ok:
                            set_phase(state_dir, phase='accepted')
                            orch._emit_lifecycle(state_dir, event='phase_transition', phase='accepted', task_id=task_id, phase_transition={'to': 'accepted'})
                            _print_json_line({'task_id': task_id, 'outcome': 'accepted', 'path': round_str})
                            exit_code = 0
                        elif no_diff:
                            set_phase(state_dir, phase='accepted')
                            orch._emit_lifecycle(state_dir, event='phase_transition', phase='accepted', task_id=task_id, phase_transition={'to': 'accepted'})
                            _print_json_line({'task_id': task_id, 'outcome': 'no_diff', 'path': round_str})
                            exit_code = 0
                        else:
                            set_phase(state_dir, phase='rejected')
                            orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                            _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': f'auto_commit_failed_r{r + 1}'})
                            exit_code = 1
                        return exit_code
                    accumulated_failures.extend(fuzz_result_n.failures)
                    latest_failures = fuzz_result_n.failures
            set_phase(state_dir, phase='decomposition')
            orch._emit_lifecycle(state_dir, event='phase_transition', phase='decomposition', task_id=task_id, phase_transition={'to': 'decomposition'})
            try:
                cur_depth = int(task.get('depth', 0) or 0)
            except (TypeError, ValueError):
                cur_depth = 0
            decomp_cfg = config.get('decomposition', {}) if isinstance(config, dict) else {}
            max_depth = decomp_cfg.get('max_depth', 3)
            if cur_depth >= max_depth:
                from harness._journal import write_jsonl_row
                try:
                    write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'phase': 'decomposition', 'task_id': task_id, 'event': 'decompose_max_depth', 'detail': f'depth {cur_depth} >= max_depth {max_depth}; terminating instead of decomposing further (SB5)', 'depth': cur_depth, 'max_depth': max_depth, 'exit': 0})
                except OSError:
                    pass
                set_phase(state_dir, phase='rejected')
                orch._emit_lifecycle(state_dir, event='phase_transition', phase='rejected', task_id=task_id, phase_transition={'to': 'rejected'})
                orch._mark_processed(state_dir, task_id)
                orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
                _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': 'decompose_max_depth', 'depth': cur_depth, 'max_depth': max_depth})
                exit_code = 1
                return exit_code
            decomp_result = decompose_task(task, latest_failures, config, code_a=revised_agent_a, code_b=revised_agent_b, depth=cur_depth)
            enqueue_subtasks(decomp_result.subtasks, state_dir)
            subtask_ids = [s.task_id for s in decomp_result.subtasks]
            update_parent_state(state_dir, task_id, subtask_ids)
            orch._mark_processed(state_dir, task_id)
            orch._emit_lifecycle(state_dir, event='task_terminal', task_id=task_id)
            _print_json_line({'task_id': task_id, 'outcome': 'rejected', 'reason': 'decomposed', 'subtasks': subtask_ids})
            exit_code = 1
            return exit_code
        except SystemExit:
            raise
        except Exception as exc:
            sys.stderr.write(f'orchestrator_worker: internal error: {exc!r}\n')
            traceback.print_exc(file=sys.stderr)
            _print_json_line({'task_id': task_id, 'outcome': 'error', 'error': repr(exc)})
            exit_code = 2
            return exit_code
        finally:
            if started_emit:
                stderr_tail = _stderr_buf.getvalue()[-256:].encode('unicode_escape').decode('ascii', errors='replace')
                _emit_lifecycle_safe(state_dir, phase='autowork', task_id=task_id, event='worker_exit', exit_code=exit_code, stderr_tail=stderr_tail)
            # CONTAIN C3: on any non-accept outcome (reject/timeout/decompose/error)
            # restore the live tree -- a stray absolute-path agent write to a target
            # only survives because no accept-path staging merge overwrote it.
            if exit_code != 0:
                _rollback_live_tree(state_dir, task.get('files_touched') or [], task_id)
                # ROLLB-E (CRASH_SAFE_TERMINAL): if an UNEXPECTED exception left the
                # task still CLAIMED as <id>.json.processing (no body terminal ran
                # _mark_processed/_mark_blocked), route it to blocked/ here so the
                # worker self-heals instead of depending solely on the daemon's
                # out-of-band _reclaim_orphan_processing sweep. No-op once a body
                # terminal already consumed the .processing file, so a cleanly
                # rejected task is NOT double-bumped. Never raises out of finally.
                try:
                    if processing.exists():
                        from harness import orchestrator as _orch
                        _orch._mark_blocked(state_dir, task_id, 'worker_crash_orphan')
                except Exception as _orphan_exc:
                    sys.stderr.write(f'orchestrator_worker: ROLLB-E orphan-route failed for {task_id}: {_orphan_exc!r}\n')
from harness.task_paths import current_task_spec_path
import contextlib
import io

def _detect_and_append_untracked_tests(state_dir: Path, task: dict[str, Any], task_id: str, processing: Path) -> None:
    """Scan for untracked test files under tests/ in the parent repo and append them to files_touched."""
    import subprocess
    import fnmatch
    try:
        cwd = str(state_dir) if state_dir.exists() else _PROJECT_ROOT
        output = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=cwd, capture_output=True, text=True, check=True)
        parent_root = Path(output.stdout.strip()).resolve()
        res = subprocess.run(['git', 'status', '--porcelain', 'tests/'], cwd=str(parent_root), capture_output=True, text=True, check=True)
        lines = res.stdout.splitlines()
        added = False
        files_touched = task.setdefault('files_touched', [])
        for line in lines:
            line = line.strip()
            if line.startswith('?? '):
                filepath = line[3:].strip().strip('"\'')
                if fnmatch.fnmatch(filepath, 'tests/test_*.py'):
                    if filepath not in files_touched:
                        files_touched.append(filepath)
                        added = True
        if added:
            with open(processing, 'w', encoding='utf-8') as fh:
                json.dump(task, fh, indent=2)
    except Exception:
        pass

def _precompute_baseline_test_results(state_dir: Path, task: dict[str, Any], task_id: str) -> None:
    """Pre-compute the baseline verification_command outcome on the unmodified
    codebase and persist it for the prompt hooks to inject into agent context.

    Resolves the task's verification_command (walking the parent-task chain
    when missing), runs it with ``/bin/bash -c 'set -o pipefail; <cmd>'`` under
    a 600s timeout, and writes ``{command, outcome, exit_code, stdout,
    stderr}`` to ``state_dir/'tasks'/'test_results'/{task_id}_baseline.json``.

    Best-effort; never raises. Edge cases handled:

      * results dir missing -> created via ``mkdir(parents=True, exist_ok=True)``;
      * no verification_command resolvable -> outcome ``no_verification_command``,
        ``exit_code`` null, command logged as empty string;
      * timeout -> outcome ``timeout``, ``exit_code`` null, stderr carries
        the truncated ``TimeoutExpired`` repr so the agent sees the cause;
      * subprocess/OS error -> outcome ``error``, ``exit_code`` null,
        stderr carries the truncated exception repr.
    """
    import subprocess
    results_dir = state_dir / 'tasks' / 'test_results'
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    out_path = results_dir / f'{task_id}_baseline.json'
    vcmd: str | None = None
    try:
        from harness.orchestrator import _resolve_verification_command
        vcmd = _resolve_verification_command(state_dir, task, task_id)
    except Exception:
        try:
            vcmd = task.get('verification_command') if isinstance(task, dict) else None
        except Exception:
            vcmd = None
    if not vcmd or not isinstance(vcmd, str) or (not vcmd.strip()):
        payload = {'task_id': task_id, 'command': vcmd if isinstance(vcmd, str) else '', 'outcome': 'no_verification_command', 'exit_code': None, 'stdout': '', 'stderr': ''}
        try:
            out_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        except OSError:
            pass
        return
    cwd = _PROJECT_ROOT
    try:
        ro = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=cwd, capture_output=True, text=True, check=False, timeout=30)
        if ro.returncode == 0 and ro.stdout.strip():
            cwd = ro.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    scrubbed_env = {k: v for k, v in os.environ.items() if not k.startswith('JANUSMASK_')}
    # H5: derive the baseline-precompute timeout from config (mirrors the accept-path
    # verify cap in orchestrator._auto_commit_accepted). The hardcoded 600 lagged the
    # 1200s synthesis window, so a slow baseline was recorded as a false 'timeout'.
    # Prefer synthesis.verification_timeout_seconds, else floor synthesis.timeout_seconds
    # at 900; load_config failure falls back to 600 (fail-safe, never unbounded).
    try:
        from harness.orchestrator import load_config as _load_config
        _vcfg = _load_config().get('synthesis', {}) or {}
        verification_timeout = int(_vcfg.get(
            'verification_timeout_seconds',
            max(900, int(_vcfg.get('timeout_seconds', 600))),
        ))
    except Exception:
        verification_timeout = 600
    exit_code: int | None
    stdout_tail = ''
    stderr_tail = ''
    outcome: str
    try:
        res = subprocess.run(['/bin/bash', '-c', f'set -o pipefail; {vcmd}'], cwd=cwd, capture_output=True, text=True, timeout=verification_timeout, env=scrubbed_env)
        exit_code = res.returncode
        stdout_tail = (res.stdout or '')[-4000:]
        stderr_tail = (res.stderr or '')[-4000:]
        outcome = 'passed' if exit_code == 0 else 'failed'
    except subprocess.TimeoutExpired as texc:
        exit_code = None
        outcome = 'timeout'
        stderr_tail = f'[baseline verification_command timed out after {verification_timeout}s: {texc!r}]'
    except (FileNotFoundError, OSError) as exc:
        exit_code = None
        outcome = 'error'
        stderr_tail = f'[baseline verification_command error: {exc!r}]'
    except Exception as exc:
        exit_code = None
        outcome = 'error'
        stderr_tail = f'[baseline verification_command error: {exc!r}]'
    payload = {'task_id': task_id, 'command': vcmd, 'outcome': outcome, 'exit_code': exit_code, 'stdout': stdout_tail, 'stderr': stderr_tail}
    try:
        out_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    except OSError:
        pass
RECONCILE_SLACK_SECONDS = 300.0


def _compute_timeout_budgets(config: dict) -> tuple[float, float]:
    """Return (HARD_TIMEOUT_SECONDS, SYNTHESIS_WINDOW_SECONDS) derived from
    synthesis.timeout_seconds. window == timeout (unchanged); hard ==
    2*timeout + slack so that after consuming one full synthesis window the
    remaining budget (window + slack) still covers a full retry window,
    permitting exactly one retry, while a second retry is refused (remaining
    == slack < window), capping the worker at <= 2 attempts. Under DAEMON
    dispatch the daemon watchdog max(1800.0, timeout + 300.0)
    (autowork_daemon.py:1373) may bind first, so the full 2-window hard
    budget is realized on FOREGROUND runs."""
    synthesis_timeout = float((config or {}).get('synthesis', {}).get('timeout_seconds', 600.0))
    return (synthesis_timeout * 2 + RECONCILE_SLACK_SECONDS, synthesis_timeout)


if __name__ == '__main__':
    sys.exit(main())