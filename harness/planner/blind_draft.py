import copy
import inspect
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from harness.orchestrator import run_both_agents
from harness.planner.brief_loader import PlanningBrief
from harness.planner.taxonomies import META_TASK_TYPES
try:
    from harness.planner.plan_validator import validate_plan as _validate_plan
except ImportError:

    def _validate_plan(plan):
        return []
logger = logging.getLogger('janusmask.planner.blind_draft')

def _resolve_outbox_artifact(agent_dir: Path, agent: str, filename: str, round_number: int=1, spawn_start_epoch: Optional[float]=None) -> Optional[Path]:
    """Find an agent's outbox-written artifact when canonical promotion didn't fire.

    Compensates for the post_tool hook drop in claude's ``-p`` mode (Claude CLI
    silently drops ``--settings`` hooks/permissions; see
    ``scripts/impl_outbox_watcher.py:4``). The agent's Write lands at
    ``<agent_dir>/workdirs/<agent>/<agent>-r<round>-*/outbox/<filename>`` per
    ``harness/orchestrator.py:189-190``. Returns the most-recently-modified
    match, or ``None`` when no match exists.
    """
    # AGENT-ISOLATION §3.7: outboxes relocated outside the repo; resolve them
    # from the shared workroot, not agent_dir/workdirs (now dead).
    from harness.paths import agent_workroot
    workdirs_root = agent_workroot() / agent
    if not workdirs_root.is_dir():
        return None
    pattern = f'{agent}-r{round_number}-*/outbox/{filename}'
    candidates = [p for p in workdirs_root.glob(pattern) if p.is_file()]
    if spawn_start_epoch is not None:
        candidates = [p for p in candidates if p.stat().st_mtime >= spawn_start_epoch]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)

def collect_agent_draft(agent: str, agent_dir: Path, state_dir: Path, elapsed: float, timeout: float, spawn_start_epoch: Optional[float]=None, min_response_seconds: float=10.0, mode: str='leaf') -> Tuple[Optional[Dict[str, Any]], str]:
    """Collect an agent's plan draft from canonical paths, falling back to
    per-spawn outbox when the post_tool promoter didn't fire.

    Search order: per-agent canonical → top-level canonical → per-spawn
    outbox glob (mtime-sorted, newest wins). Returns ``(draft, "ok")`` on
    success, ``(None, "timeout"|"crashed"|"invalid")`` on the various
    failure modes (preserves the prior closure semantics).

    ``mode`` selects the validation schema: ``"leaf"`` (default) validates
    with the leaf plan validator; ``"epic"`` validates the draft against the
    child-brief schema via ``validate_child_brief_plan``.
    """
    draft_file = agent_dir / 'planning' / 'sessions' / f'{agent}_draft.json'
    if not draft_file.exists():
        draft_file = state_dir / 'planning' / 'sessions' / f'{agent}_draft.json'
    if not draft_file.exists():
        outbox_match = _resolve_outbox_artifact(agent_dir, agent, 'plan_draft.json', round_number=1, spawn_start_epoch=spawn_start_epoch)
        if outbox_match is not None:
            logger.info('%s draft recovered from per-spawn outbox: %s', agent, outbox_match)
            draft_file = outbox_match
    if not draft_file.exists():
        if elapsed >= timeout - 1.0:
            return (None, 'timeout')
        return (None, 'crashed')
    if spawn_start_epoch is not None:
        try:
            submission_mtime = draft_file.stat().st_mtime
        except OSError:
            submission_mtime = spawn_start_epoch + min_response_seconds
        latency = submission_mtime - spawn_start_epoch
        if latency < min_response_seconds:
            logger.warning('%s draft latency %.2fs < threshold %.2fs; treating as suspect_hallucination', agent, latency, min_response_seconds)
            return (None, 'suspect_hallucination')
    try:
        with open(draft_file, 'r', encoding='utf-8') as f:
            draft = json.load(f)
    except Exception:
        return (None, 'invalid')
    if mode == 'epic':
        # Local import avoids a module-level circular dependency between the
        # planner validator and the blind-draft collector.
        from harness.planner.plan_validator import validate_child_brief_plan
        violations = validate_child_brief_plan(draft)
    else:
        violations = _validate_plan(draft)
    if violations:
        logger.warning(f'{agent} draft invalid: %s', violations)
        return (None, 'invalid')
    return (draft, 'ok')

@dataclass
class BlindDraftResult:
    claude_draft: Optional[Dict[str, Any]]
    claude_status: str
    gemini_draft: Optional[Dict[str, Any]]
    gemini_status: str

class _PerAgentConfig(dict):
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

def run_blind_drafts(brief: PlanningBrief, config: Dict[str, Any], state_dir: Path) -> BlindDraftResult:
    '''Spawns both agents in planning mode and returns their drafts.'''
    planning_dir = state_dir / 'planning'
    planning_dir.mkdir(parents=True, exist_ok=True)
    brief_path = planning_dir / 'brief.json'
    with open(brief_path, 'w', encoding='utf-8') as f:
        json.dump({'title': brief.title, 'scope': brief.scope, 'non_goals': brief.non_goals, 'inputs': brief.inputs, 'deliverables': brief.deliverables, 'raw_text': brief.raw_text, 'source_path': str(brief.source_path), 'sha256': brief.sha256}, f, indent=2)
    claude_dir = planning_dir / 'sessions' / 'claude'
    gemini_dir = planning_dir / 'sessions' / 'gemini'
    claude_dir.mkdir(parents=True, exist_ok=True)
    gemini_dir.mkdir(parents=True, exist_ok=True)
    derived_config = _PerAgentConfig(copy.deepcopy(config), claude_dir, gemini_dir)
    for agent in ['claude', 'gemini']:
        derived_config.setdefault('agents', {}).setdefault(agent, {}).setdefault('env', {})
        derived_config['agents'][agent]['env']['JANUSMASK_MODE'] = 'planning'
    timeout = derived_config.get('planning_timeout_seconds', 1800)
    derived_config.setdefault('synthesis', {})['timeout_seconds'] = timeout
    old_env = os.environ.get('JANUSMASK_MODE')
    os.environ['JANUSMASK_MODE'] = 'planning'
    prompt = f'''You are a planning agent. Your task is to draft a plan of JanusMask tasks that implements the planning brief titled "{brief.title}".\n\nScope: {brief.scope}\nNon-goals: {brief.non_goals}\nExpected deliverables: {brief.deliverables}\nRelevant inputs to investigate: {brief.inputs}\n\n----- BRIEF (full markdown body) -----\n{brief.raw_text}\n----- END BRIEF -----\n\nYour plan must directly address the concerns in this brief — do NOT substitute your own unrelated agenda. Each task in the plan must map to a concern or deliverable from the brief; a task that does not trace back to the brief is a bug.\n\nSubmit your plan by writing a single JSON file at:\n    {{OUTBOX_PATH}}/plan_draft.json\nWriting this file IS how you submit; the harness intercepts the Write via a PostToolUse/AfterTool hook, validates the JSON, and persists it for the planner to pick up. The MCP janusmask execute tool is NOT registered in this worker session — only file read/write and read-only exploration tools (Read, Glob, Grep) are available.\n\nIf the PreToolUse hook rejects the Write with a validation error, fix the JSON and Write the same path again — the gate is single-shot only on accepted submissions.\n\nIMPORTANT SCHEMA REQUIREMENTS for plan_draft.json:\nThe file MUST contain a JSON object with a 'tasks' array. Every task in the array MUST be a complete object with the following structure:\n{{\n  "task_id": "...",\n  "title": "...",\n  "meta_task_type": "refactor", // REQUIRED non-empty string. Choose the best fit from the canonical taxonomy: {', '.join(sorted(META_TASK_TYPES))}\n  "priority": "...",\n  "dependencies": [], // Array of task_ids this depends on\n  "files_touched": [],\n  "acceptance_criteria": [],\n  "spec_author": null, // MUST be exactly null (not a string)\n  "estimated_complexity": "...",\n  "verification_command": "...",\n  "spec": {{\n    "objective": "...",\n    "functional_requirements": ["..."], // Minimum 1 requirement\n    "interfaces": "...",\n    "edge_cases": ["..."],\n    "non_goals": ["..."],\n    "implementation_notes": "..."\n  }},\n  "test_spec": {{\n    "unit_tests": [{{"name": "..."}}], // Array of objects. Length MUST be >= len(functional_requirements)\n    "integration_tests": [{{"name": "..."}}], // Array of objects\n    "property_tests": [{{"name": "..."}}], // Array of objects\n    "regression_tests": [{{"name": "..."}}], // Array of objects\n    "minimum_test_count": 10, // MUST be >= 1.5 * len(functional_requirements)\n    "test_data_requirements": "..."\n  }},\n  "token_budget_ratio": {{\n    "implementation_tokens": 100,\n    "test_tokens": 200, // MUST be >= 1.5 * implementation_tokens. If impl is 0, test_tokens must be > 0\n    "note": "..."\n  }},\n  "attribution_metadata": {{\n    "proposed_by": "agent",\n    "reconciled": false,\n    "diff_resolution": ""\n  }}\n}}\n\nIf validation fails repeatedly, simplify the DAG and read the gate's rejection reason carefully — bash and arbitrary Python are BLOCKED, so you cannot script schema generation; emit JSON directly that matches the structure above.'''
    import time
    start_time = time.monotonic()
    spawn_wall_start = time.time()
    c_draft_path = state_dir / 'planning' / 'sessions' / 'claude_draft.json'
    g_draft_path = state_dir / 'planning' / 'sessions' / 'gemini_draft.json'
    try:
        if c_draft_path.exists() and g_draft_path.exists():
            logger.info('Both drafts already exist, skipping blind draft execution.')
            elapsed = 0
        else:
            _c_code, _g_code = run_both_agents(prompt, prompt, derived_config, state_dir, 1, 'planning')
            elapsed = time.monotonic() - start_time
    finally:
        if old_env is None:
            del os.environ['JANUSMASK_MODE']
        else:
            os.environ['JANUSMASK_MODE'] = old_env
    mode = 'epic' if getattr(brief, 'epic', False) else 'leaf'
    c_draft, c_status = collect_agent_draft('claude', claude_dir, state_dir, elapsed, timeout, spawn_start_epoch=spawn_wall_start, mode=mode)
    g_draft, g_status = collect_agent_draft('gemini', gemini_dir, state_dir, elapsed, timeout, spawn_start_epoch=spawn_wall_start, mode=mode)
    return BlindDraftResult(claude_draft=c_draft, claude_status=c_status, gemini_draft=g_draft, gemini_status=g_status)