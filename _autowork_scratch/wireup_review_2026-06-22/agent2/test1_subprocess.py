"""LIMITATION 1 — SUBPROCESS.
A LIVE_ROOT that reaches the new symbol by spawning a CHILD python process.
settrace in the parent never sees the child's frames -> FALSE REJECT.

Faithful-to-brief scenario: the new top-level callable lives in a module; the
'live entrypoint' reaches it only by spawning `python -c "import mod; mod.sym()"`.
This is precisely how a worker reaches code: orchestrator spawns
orchestrator_worker as a subprocess in production.
"""
import sys, os, subprocess, tempfile, textwrap
sys.path.insert(0, os.path.dirname(__file__))
from faithful_primitive import observe_symbol_execution

# A module with the NEW top-level callable.
mod_src = textwrap.dedent('''
    def child_reached_symbol():
        # genuinely WIRED: this is the work the spawned child does
        return "ran in child"
''')

tmpd = tempfile.mkdtemp(prefix="subproc_")
modpath = os.path.join(tmpd, "spawned_mod.py")
with open(modpath, "w") as f:
    f.write(mod_src)


def live_entrypoint_that_spawns():
    # The real reach is in a child process (mirrors orchestrator -> worker spawn).
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); import spawned_mod; print(spawned_mod.child_reached_symbol())" % tmpd],
        cwd=tmpd, capture_output=True, text=True,
    )
    return r.stdout.strip()


with observe_symbol_execution(['child_reached_symbol']) as obs:
    out = live_entrypoint_that_spawns()

print("child process stdout (proves the symbol REALLY executed):", repr(out))
print("observer says executed (want True if sound; FALSE = blind spot):",
      obs.executed('child_reached_symbol'))
print("VERDICT: FALSE REJECT" if (out == "ran in child" and not obs.executed('child_reached_symbol'))
      else "VERDICT: observed")
