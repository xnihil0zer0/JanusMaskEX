import os
import pathlib
from harness.hooks._paths import _DEFAULT_PROJECT_DIR

def project_dir() -> pathlib.Path:
    raw = os.environ.get("JANUSMASK_PROJECT_DIR")
    if not raw:
        raw = os.environ.get("CLAUDE_PROJECT_DIR")
    if raw:
        return pathlib.Path(raw).resolve()
    return _DEFAULT_PROJECT_DIR
