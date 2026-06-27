"""Live e2e against the COMMITTED harness.tmux_worker (real jail, real PTY, real claude)."""
import os, tempfile, time, yaml
from pathlib import Path
import harness.tmux_worker as tw

REPO = "/home/xnihil0zer0/JanusMaskJR"
cfg = yaml.safe_load(open(os.path.join(REPO, "harness/config.yaml")))
cfg["agents"]["claude"]["command"] = cfg["agents"]["claude"]["command"].replace("${PROJECT_ROOT}", REPO)
cfg["agents"]["claude"]["args"] = [a.replace("${PROJECT_ROOT}", REPO).replace("${CONFIG_DIR}", os.path.join(REPO,"config")) for a in cfg["agents"]["claude"].get("args", [])]

work_dir = tempfile.mkdtemp(prefix="live_committed_")
(Path(work_dir)/"outbox").mkdir(parents=True, exist_ok=True)
os.environ.pop("JANUSMASK_WORKING_DIR", None)
env = {"JANUSMASK_WORK_DIR": work_dir, "JANUSMASK_STATE_DIR": os.path.join(REPO,"state"),
       "JANUSMASK_TASK_ID": "live-committed", "HOME": os.environ["HOME"]}
prompt = ("You are a build worker. Write a file at outbox/submission.py whose entire contents are exactly:\n\n"
          "print('COMMITTED_MODULE_OK')\n\nUse the Write tool. Create no other files. Then you are finished.")
t0=time.time()
proc = tw.spawn_claude_tmux("claude", prompt, env, cfg, dbus_sock=None)
dt=time.time()-t0
sub = Path(work_dir)/"outbox"/"submission.py"
ok = sub.exists() and "COMMITTED_MODULE_OK" in sub.read_text()
print(f"[live] returned {type(proc).__name__} poll={proc.poll()} in {dt:.0f}s")
print(f"[live] deliverable exists={sub.exists()} content={sub.read_text() if sub.exists() else None!r}")
print("[live]", "PASS" if ok else "FAIL")
