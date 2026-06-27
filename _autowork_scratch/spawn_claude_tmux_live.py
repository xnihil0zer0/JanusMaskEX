"""Live validation of harness.tmux_worker.spawn_claude_tmux (the wired entrypoint).

Mimics what orchestrator.spawn_agent passes, in an isolated temp work_dir, with the
REAL bwrap jail + real interactive claude. Confirms the deliverable (outbox file) lands.

Run: PYTHONPATH=. python _autowork_scratch/spawn_claude_tmux_live.py
"""
from __future__ import annotations
import os, tempfile, time, yaml
from pathlib import Path

import importlib.util as _ilu, sys as _sys
_spec = _ilu.spec_from_file_location("tmux_worker_ref", "/home/xnihil0zer0/JanusMaskJR/_autowork_scratch/tmux_worker_ref.py")
tw = _ilu.module_from_spec(_spec); _sys.modules["tmux_worker_ref"] = tw; _spec.loader.exec_module(tw)

REPO = "/home/xnihil0zer0/JanusMaskJR"
cfg = yaml.safe_load(open(os.path.join(REPO, "harness/config.yaml")))
# resolve ${PROJECT_ROOT} in the claude command/args the way the harness does
claude_cmd = cfg["agents"]["claude"]["command"].replace("${PROJECT_ROOT}", REPO)
cfg["agents"]["claude"]["command"] = claude_cmd
cfg["agents"]["claude"]["args"] = [
    a.replace("${PROJECT_ROOT}", REPO).replace("${CONFIG_DIR}", os.path.join(REPO, "config"))
    for a in cfg["agents"]["claude"].get("args", [])
]

work_dir = tempfile.mkdtemp(prefix="spawn_tmux_live_")
state_dir = os.path.join(REPO, "state")
(Path(work_dir) / "outbox").mkdir(parents=True, exist_ok=True)

env = {
    "JANUSMASK_WORK_DIR": work_dir,
    "JANUSMASK_STATE_DIR": state_dir,
    "JANUSMASK_TASK_ID": "spawn-tmux-live",
    "HOME": os.environ["HOME"],
}
# point repo_root resolution at self (no external working dir)
os.environ.pop("JANUSMASK_WORKING_DIR", None)

prompt = (
    "You are a build worker. Write a file at outbox/submission.py (relative to your "
    "current working directory) whose entire contents are exactly:\n\n"
    "print('TMUX_SPAWN_OK')\n\n"
    "Use the Write tool. Create no other files. Then you are finished."
)

print(f"[live] work_dir={work_dir}")
print(f"[live] claude_cmd={claude_cmd}")
t0 = time.time()
proc = tw.spawn_claude_tmux("claude", prompt, env, cfg, dbus_sock=None)
dt = time.time() - t0
print(f"[live] spawn_claude_tmux returned {type(proc).__name__} poll={proc.poll()} in {dt:.0f}s")

sub = Path(work_dir) / "outbox" / "submission.py"
exists = sub.exists()
content = sub.read_text() if exists else None
print(f"[live] outbox/submission.py exists={exists} content={content!r}")
print("[live]", "PASS" if (exists and content and "TMUX_SPAWN_OK" in content) else "FAIL")
