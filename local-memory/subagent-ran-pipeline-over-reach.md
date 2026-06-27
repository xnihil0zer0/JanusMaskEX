---
name: subagent-ran-pipeline-over-reach
description: CORRECTED — the worker's post-commit `not_found` is the blue-green os.execv exec-handover firing, NOT a skipped/rogue run. Don't misread it.
metadata:
  node_type: memory
  type: feedback
  originSessionId: 5dd8d8ba-7994-41c2-99c8-cdfd25cddfb0
---

**CORRECTION (this memory originally, wrongly, blamed a sub-agent — retracted).**

During REV5 execution (2026-05-30) I ran the M7 pipeline via `python -m harness.orchestrator_worker --task-id M7_WATCHDOG_TIMEOUT_WRITE`. Its captured stdout was only `{"skipped": "not_found"}` + exit 0, yet full processing state existed (both agents submitted, `e1f0435` committed). I leapt to "a sub-agent ran the worker behind my back." **That was wrong.**

**Root cause — the blue-green "Process Exec Handover" (commit `3d553e2`).** On accept, `_auto_commit_accepted` (orchestrator.py ~1672-1693): `_mark_processed` moves `state/tasks/<id>.json` → `processed/`, `merge_staging_to_parent` fast-forwards the live tree, then — if NOT under pytest (`"pytest" in sys.modules or PYTEST_CURRENT_TEST`) — calls `perform_process_handover` (orchestrator.py:1319) → `os.execv([python] + sys.argv)`. That **hot-swaps the running process (same PID) into the just-merged code, re-running the SAME argv** (`--task-id <id>`). The re-exec'd worker finds the task already in `processed/` → prints `{"skipped":"not_found"}` → exit 0. So a CLEAN, SUCCESSFUL self-edit run looks, from captured stdout, like a worker that found nothing.

**Why I was sure it wasn't a sub-agent:** I had captured `HEAD=efdd998` AFTER the sub-agent returned but BEFORE launching my worker; `e1f0435` didn't exist yet, so the sub-agent couldn't have committed it. Single `auto_commit` ledger row; one reflog fast-forward. My own launch did it.

**How to apply:**
- Do NOT treat a worker's `{"skipped":"not_found"}` as "nothing happened." After an accept it's the EXPECTED signature of the exec-handover. Check `git log`/the `auto_commit` ledger row + `state/tasks/processed/<id>.json` before concluding a run was skipped.
- The verbose pipeline logging does NOT go to the worker's stdout (it goes to logging handlers / `gemini_stream.jsonl` etc.); `os.execv` pre-empts the original process's final print, so only the re-exec'd skip line survives in captured stdout.
- Containment still held (tree clean, memory untouched, `:237`/`:1818` intact, only the approved 4-line diff). The earlier "harden sub-agent prompts" advice is still fine practice, but the incident that motivated it did not actually occur. See [[claude-jail-fix-first-accept-commit]].
- Separately FLAGGED: `merge_staging_to_parent` fails-closed ("Fast-forward merge failed: local changes would be overwritten … Aborting") when the live tree is DIRTY at merge time — bit `AUTOWORK_DAEMON_SAFEGUARDS`, `RB_jr_slice_*`. Keep the parent tree clean before a pipeline run. A leftover staging worktree `/tmp/jmjr_parent` was also found orphaned.
