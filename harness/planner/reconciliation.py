import copy
import inspect
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from harness.orchestrator import run_both_agents
from harness.planner.diff_model import PlanDiff
from harness.planner.diff_model import DiffItem
from harness.planner.diff_model import DiffKind
from harness.track_record import TrackRecordUnavailable
logger = logging.getLogger('janusmask.planner.reconciliation')

@dataclass
class ReconciliationResult:
    merged_tasks: List[Dict[str, Any]]
    unresolved_items: List[DiffItem]
    per_agent_errors: Dict[str, List[str]]
    resolution_policy: str = 'flag_for_human'

class _ReconciliationConfig(dict):
    """A dictionary that dynamically returns a different state_dir depending on the caller."""

    def __init__(self, base_config: Dict[str, Any], claude_dir: Path, gemini_dir: Path):
        super().__init__(base_config)
        self._claude_dir = claude_dir
        self._gemini_dir = gemini_dir

    def get(self, key: str, default: Any=None) -> Any:
        if key == 'state_dir':
            for frame_info in inspect.stack():
                if frame_info.function in ('run_agent_phase', 'spawn_agent'):
                    agent = frame_info.frame.f_locals.get('agent')
                    if agent == 'claude':
                        return str(self._claude_dir)
                    if agent == 'gemini':
                        return str(self._gemini_dir)
        return super().get(key, default)

    def __getitem__(self, key: str) -> Any:
        if key == 'state_dir':
            return self.get('state_dir')
        return super().__getitem__(key)

def _log_reconciliation_decision(log_file: Path, diff_item_id: str, decision: str, policy: Optional[str]=None) -> None:
    entry = {'diff_item_id': diff_item_id, 'decision': decision}
    if policy is not None:
        entry['policy'] = policy
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')

def _reconciliation_prompt(mode: str = 'leaf') -> str:
    """Return the reconciliation prompt text for the given planning mode.

    Leaf mode (the default, and any non-epic value) returns the inline
    reconcile prompt byte-for-byte. Epic mode loads
    prompts/epic_reconciliation_prompt.md, falling back to the leaf prompt
    when that file is absent. The prompt file may contain literal JSON
    braces, so it is returned verbatim (no str.format).
    """
    if mode == 'epic':
        epic_path = Path(__file__).parent / 'prompts' / 'epic_reconciliation_prompt.md'
        try:
            return epic_path.read_text(encoding='utf-8')
        except OSError:
            pass
    return 'You are a reconciliation agent. Two planning agents produced divergent task plans for the same brief; the system needs your stance on each divergent item before merging.\n\nRead the current diff from:\n    {STATE_DIR}/planning/current_diff.json\nEach entry under `items` has a `diff_item_id` plus the competing task definitions from claude and gemini.\n\nSubmit your stances by writing a single JSON file at:\n    {OUTBOX_PATH}/reconciliation.json\nWriting this file IS how you submit; the harness intercepts the Write via a PostToolUse/AfterTool hook and persists the JSON for the planner. The MCP janusmask execute tool is NOT registered in this worker session — only file read/write and read-only exploration tools (Read, Glob, Grep) are available.\n\nIf the PreToolUse hook rejects the Write with a validation error, fix the JSON and Write the same path again — the gate is single-shot only on accepted submissions.\n\nIMPORTANT SCHEMA REQUIREMENTS for reconciliation.json:\nThe file MUST contain a JSON object with a `responses` array. You MUST provide one entry per divergent item in current_diff.json. Each entry MUST have:\n{\n  "diff_item_id": "<the diff_item_id from current_diff.json>",\n  "stance": "defend" | "concede" | "amend"\n}\n'

def run_reconciliation(diff: PlanDiff, claude_draft: Dict[str, Any], gemini_draft: Dict[str, Any], config: Dict[str, Any], state_dir: Path, mode: str = 'leaf') -> ReconciliationResult:
    """Run a single-round reconciliation using track-record tiebreaker."""
    merged_tasks: List[Dict[str, Any]] = []
    unresolved_items: List[DiffItem] = []
    per_agent_errors: Dict[str, List[str]] = {'claude': [], 'gemini': []}
    planning_dir = state_dir / 'planning'
    planning_dir.mkdir(parents=True, exist_ok=True)
    log_dir = state_dir.parent / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    reconciliation_log_file = log_dir / 'planner_reconciliation.jsonl'
    if not diff.items:
        return ReconciliationResult(merged_tasks, unresolved_items, per_agent_errors)
    divergent_items: List[DiffItem] = []
    for item in diff.items:
        if item.kind == DiffKind.convergent:
            if item.claude_task:
                merged_tasks.append(copy.deepcopy(item.claude_task))
            elif item.gemini_task:
                merged_tasks.append(copy.deepcopy(item.gemini_task))
        elif item.kind in (DiffKind.divergent, DiffKind.ambiguous_match, DiffKind.claude_only, DiffKind.gemini_only):
            divergent_items.append(item)
    if not divergent_items:
        return ReconciliationResult(merged_tasks, unresolved_items, per_agent_errors)
    current_diff_json = diff.to_json()
    main_diff_path = planning_dir / 'current_diff.json'
    with open(main_diff_path, 'w', encoding='utf-8') as f:
        f.write(current_diff_json)
    claude_dir = planning_dir / 'sessions' / 'claude'
    gemini_dir = planning_dir / 'sessions' / 'gemini'
    claude_dir.mkdir(parents=True, exist_ok=True)
    gemini_dir.mkdir(parents=True, exist_ok=True)
    for agent_dir in (claude_dir, gemini_dir):
        agent_planning_dir = agent_dir / 'planning'
        agent_planning_dir.mkdir(parents=True, exist_ok=True)
        with open(agent_planning_dir / 'current_diff.json', 'w', encoding='utf-8') as f:
            f.write(current_diff_json)
    derived_config = _ReconciliationConfig(copy.deepcopy(config), claude_dir, gemini_dir)
    for agent in ['claude', 'gemini']:
        derived_config.setdefault('agents', {}).setdefault(agent, {}).setdefault('env', {})
        derived_config['agents'][agent]['env']['JANUSMASK_MODE'] = 'reconciliation'
    timeout = derived_config.get('planning_timeout_seconds', 1800)
    derived_config.setdefault('synthesis', {})['timeout_seconds'] = timeout
    old_env = os.environ.get('JANUSMASK_MODE')
    os.environ['JANUSMASK_MODE'] = 'reconciliation'
    prompt = _reconciliation_prompt(mode)
    spawn_wall_start = time.time()
    try:
        _c_code, _g_code = run_both_agents(prompt, prompt, derived_config, state_dir, 1, 'reconciliation')
    finally:
        if old_env is None:
            del os.environ['JANUSMASK_MODE']
        else:
            os.environ['JANUSMASK_MODE'] = old_env

    def collect_reconciliation_response(agent: str, agent_dir: Path, spawn_start_epoch: Optional[float]=None) -> tuple[Dict[str, str], bool, bool]:
        recon_file = agent_dir / 'planning' / 'sessions' / f'{agent}_reconciliation.json'
        if not recon_file.exists():
            from harness.planner.blind_draft import _resolve_outbox_artifact
            outbox_match = _resolve_outbox_artifact(agent_dir, agent, 'reconciliation.json', round_number=1, spawn_start_epoch=spawn_start_epoch)
            if outbox_match is None:
                return ({}, False, False)
            logger.info('%s reconciliation recovered from per-spawn outbox: %s', agent, outbox_match)
            recon_file = outbox_match
        try:
            with open(recon_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            responses = data.get('responses', [])
            stances = {}
            for res in responses:
                diff_item_id = res.get('diff_item_id')
                stance = res.get('stance')
                if diff_item_id and stance:
                    stances[diff_item_id] = stance
            return (stances, True, False)
        except Exception:
            return ({}, True, True)
    claude_stances, claude_responded, claude_parse_failed = collect_reconciliation_response('claude', claude_dir, spawn_start_epoch=spawn_wall_start)
    gemini_stances, gemini_responded, gemini_parse_failed = collect_reconciliation_response('gemini', gemini_dir, spawn_start_epoch=spawn_wall_start)
    if claude_parse_failed:
        per_agent_errors['claude'].append('reconciliation_json_unparseable')
    if gemini_parse_failed:
        per_agent_errors['gemini'].append('reconciliation_json_unparseable')
    valid_diff_ids = {item.diff_item_id for item in diff.items}
    for agent, stances in [('claude', claude_stances), ('gemini', gemini_stances)]:
        for diff_item_id in list(stances.keys()):
            if diff_item_id not in valid_diff_ids:
                per_agent_errors[agent].append(f'unknown diff_item_id: {diff_item_id}')
                del stances[diff_item_id]
    try:
        from harness.track_record import track_record_tiebreaker
    except ImportError:

        def track_record_tiebreaker(meta_task_type: str, diff_item: DiffItem) -> str:
            raise TrackRecordUnavailable('harness.track_record module not available')
    reconciliation_cfg = config.get('reconciliation', {})
    unresolved_policy = reconciliation_cfg.get('unresolved_policy', 'flag_for_human')
    for item in divergent_items:
        c_silent = not claude_responded
        g_silent = not gemini_responded
        c_parse_failed = claude_parse_failed
        g_parse_failed = gemini_parse_failed
        if c_silent and g_silent:
            unresolved_items.append(item)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'unresolved_policy', 'both_agents_silent')
            continue
        if c_parse_failed and g_parse_failed:
            unresolved_items.append(item)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'unresolved_policy', 'both_agents_parse_failed')
            continue
        c_stance = claude_stances.get(item.diff_item_id, 'concede')
        g_stance = gemini_stances.get(item.diff_item_id, 'concede')
        c_task = copy.deepcopy(item.claude_task) if item.claude_task else None
        g_task = copy.deepcopy(item.gemini_task) if item.gemini_task else None
        if c_silent:
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'silent_concede', 'claude_silent')
            c_stance = 'concede'
        elif c_parse_failed:
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'parse_failed', 'claude_reconciliation_json_unparseable')
            c_stance = 'concede'
        if g_silent:
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'silent_concede', 'gemini_silent')
            g_stance = 'concede'
        elif g_parse_failed:
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'parse_failed', 'gemini_reconciliation_json_unparseable')
            g_stance = 'concede'
        if c_stance == 'defend' and c_task is None:
            c_stance = 'concede'
        if g_stance == 'defend' and g_task is None:
            g_stance = 'concede'
        if c_stance == 'defend' and g_stance == 'concede':
            if c_task:
                merged_tasks.append(c_task)
            elif g_task:
                merged_tasks.append(g_task)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'auto')
            continue
        if c_stance == 'concede' and g_stance == 'defend':
            if g_task:
                merged_tasks.append(g_task)
            elif c_task:
                merged_tasks.append(c_task)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'auto')
            continue
        if c_stance == 'concede' and g_stance == 'concede':
            if c_task:
                merged_tasks.append(c_task)
            elif g_task:
                merged_tasks.append(g_task)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'auto')
            continue
        meta_task_type = 'unknown'
        if item.claude_task:
            meta_task_type = item.claude_task.get('meta_task_type', 'unknown')
        elif item.gemini_task:
            meta_task_type = item.gemini_task.get('meta_task_type', 'unknown')
        tie_result = 'tie'
        try:
            tie_result = track_record_tiebreaker(meta_task_type, item)
        except TrackRecordUnavailable:
            raise
        except Exception:
            tie_result = 'tie'
        if tie_result == 'claude' and c_task:
            merged_tasks.append(c_task)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'tiebreaker')
        elif tie_result == 'gemini' and g_task:
            merged_tasks.append(g_task)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'tiebreaker')
        elif unresolved_policy == 'prefer_claude':
            if c_task:
                merged_tasks.append(c_task)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'unresolved_policy', 'prefer_claude')
        elif unresolved_policy == 'prefer_gemini':
            if g_task:
                merged_tasks.append(g_task)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'unresolved_policy', 'prefer_gemini')
        elif unresolved_policy == 'drop':
            unresolved_items.append(item)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'unresolved_policy', 'drop')
        else:
            unresolved_items.append(item)
            _log_reconciliation_decision(reconciliation_log_file, item.diff_item_id, 'unresolved_policy', 'flag_for_human')
    return ReconciliationResult(merged_tasks, unresolved_items, per_agent_errors)

import time