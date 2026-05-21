import json
from pathlib import Path

def compute_brief_status(repo_root: Path, state_dir: Path) -> list[dict]:
    raise NotImplementedError

def compute_autowork_eligibility(repo_root: Path, state_dir: Path, now=None, max_age_sec: int=604800) -> dict:
    raise NotImplementedError

def compute_autowork_backlog(repo_root: Path, state_dir: Path, now=None, max_age_sec: int=604800) -> dict:
    raise NotImplementedError