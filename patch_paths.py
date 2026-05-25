import ast
import os

with open("harness/hooks/_paths.py", "r") as f:
    content = f.read()

impl = """
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
"""

# wait, simpler, just append the implementation to the bottom of the file!
# python uses the last defined function with the same name.
content = content + "\n\n" + impl

with open("harness/hooks/_paths_patched.py", "w") as f:
    f.write(content)
