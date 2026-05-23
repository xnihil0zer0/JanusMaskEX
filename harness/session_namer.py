"""Session namer module for managing submission and feedback filenames."""
from pathlib import Path

def generate_submission_filename(agent: str, round_number: int, task_id: str, timestamp_str: str | None=None) -> str:
    """
    Generate a submission filename.

    Args:
        agent: Agent identifier
        round_number: Round number
        task_id: Task identifier
        timestamp_str: Optional timestamp string

    Returns:
        Submission filename in format:
        {agent}_round{round_number}_{task_id}_{timestamp_str}_submission.json
        (omits timestamp component if None)
    """
    if timestamp_str:
        return f'{agent}_round{round_number}_{task_id}_{timestamp_str}_submission.json'
    return f'{agent}_round{round_number}_{task_id}_submission.json'

def generate_feedback_filename(agent: str, round_number: int, task_id: str, timestamp_str: str | None=None) -> str:
    """
    Generate a feedback filename.

    Args:
        agent: Agent identifier
        round_number: Round number
        task_id: Task identifier
        timestamp_str: Optional timestamp string

    Returns:
        Feedback filename in format:
        {task_id}_round{round_number}_{agent}_{timestamp_str}_feedback.json
        (omits timestamp component if None)
    """
    raise NotImplementedError

def get_latest_submission(sessions_dir: Path, agent: str, round_number: int, task_id: str) -> Path | None:
    """
    Get the most recently modified submission file matching the given parameters.

    Args:
        sessions_dir: Path to the sessions directory
        agent: Agent identifier
        round_number: Round number
        task_id: Task identifier

    Returns:
        Path to the most recently modified submission file, or None if not found
    """
    pattern = f'{agent}_round{round_number}_{task_id}*_submission.json'
    matches = list(sessions_dir.glob(pattern))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)

def get_latest_feedback(sessions_dir: Path, agent: str, task_id: str) -> Path | None:
    """
    Get the most recently modified feedback file matching the given parameters.

    Args:
        sessions_dir: Path to the sessions directory
        agent: Agent identifier
        task_id: Task identifier

    Returns:
        Path to the most recently modified feedback file, or None if not found
    """
    pattern = f'{task_id}_round*_{agent}*_feedback.json'
    matches = list(sessions_dir.glob(pattern))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)

def feedback_glob_pattern(agent: str, task_id: str | None) -> str:
    """Glob pattern matching all rounds' feedback files for this (task, agent).

    Used by cross_examiner.clear_feedback_files; kept here so the filename
    contract lives in exactly one module.
    """
    raise NotImplementedError