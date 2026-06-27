"""Debug: build the jailed interactive-claude argv exactly like spawn_claude_tmux,
launch it in tmux, wait, and CAPTURE the pane to see why claude isn't running."""
from __future__ import annotations
import os, shutil, subprocess, time, yaml
from pathlib import Path
from overseer import tmux_session, tmux_seams
from harness import agent_jail
from harness.paths import PROJECT_ROOT

REPO = str(PROJECT_ROOT)
cfg = yaml.safe_load(open(os.path.join(REPO, "harness/config.yaml")))
claude_bin = cfg["agents"]["claude"]["command"].replace("${PROJECT_ROOT}", REPO)
args = [a.replace("${PROJECT_ROOT}", REPO).replace("${CONFIG_DIR}", os.path.join(REPO,"config")) for a in cfg["agents"]["claude"]["args"]]

import tempfile
work_dir = tempfile.mkdtemp(prefix="tmuxjaildbg_")
state_dir = os.path.join(REPO, "state")
(Path(work_dir)/"outbox").mkdir(parents=True, exist_ok=True)
config_dir = os.path.join(work_dir, ".tmuxcfg")
copied = tmux_seams.seed_config_dir(config_dir, home=os.environ["HOME"], copy=shutil.copy2, exists=os.path.exists, makedirs=lambda d: os.makedirs(d, exist_ok=True))
print("seeded:", copied)

interactive = tmux_seams.build_interactive_argv(claude_bin, config_dir, model="opus", tools=["Read","Glob","Grep","Write"])
jailed = agent_jail.build_jail_argv(interactive, repo_root=REPO, work_dir=work_dir, state_dir=state_dir, dbus_proxy_socket=None)
print("JAILED ARGV (first 12):", jailed[:12])
print("... tail:", jailed[-10:])

Path(work_dir, ".tmux_prompt.txt").write_text("Write a file outbox/submission.py containing exactly: print('OK')\n")

def tmux_exec(argv): return subprocess.run(list(argv), capture_output=True, text=True, timeout=120).stdout
session = f"jaildbg_{os.getpid()}"
ready = tmux_session.start_session(session, jailed, work_dir, tmux_exec=tmux_exec, sleep=time.sleep, max_dialog_rounds=8, settle=0.5)
print("start_session ready=", ready)
time.sleep(6)
snap = tmux_exec(tmux_session.build_capture_argv(session))
print("=== PANE SNAPSHOT ===")
print(snap[-3000:])
tmux_session.kill_session(session, tmux_exec=tmux_exec)
