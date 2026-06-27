---
name: stale-sidecar-precedence-gotcha
description: "Re-dispatching a re-spec'd task fails if a prior attempt's state/output sidecar survives — patches.json/files.json take precedence over .py"
metadata: 
  node_type: memory
  type: project
  originSessionId: c1635191-5f48-4117-ab41-8bcebeef312b
---

When re-dispatching a task whose `task_id` was used by a PRIOR attempt with a different `partial_edit` mode, **clean `state/output/<task_id>.{patches,files}.json` first**.

`git_integration.commit_accepted_output` checks sidecars in precedence order: `<task_id>.patches.json` (`:675`) → `<task_id>.files.json` (`:678`) → legacy singular `<task_id>.py`. These sidecars are NOT cleared between dispatches.

**Concrete failure (2026-06-03, rev26_p5b_config_keys):** re-spec'd a `partial_edit:true` task to whole-file `partial_edit:false` (non-`.py` config.yaml). New dispatch wrote a fresh `.py`, but the PRIOR attempt's stale `.patches.json` survived in `state/output/` → `:675` routed the YAML through `_commit_accepted_output_patches` → `ast.parse` → `auto-commit FAILED: invalid syntax (<unknown>, line 1)`. This looked like a harness bug but was pure stale residue. Fix = `rm state/output/<id>.{patches,files,py}.json` + clean `state/sessions/*<id>_submission.json` + re-stage taskspec (it gets MOVED to `state/tasks/processed/` on terminal, so remove the processed marker and re-create in `state/tasks/`).

**How to read a non-`.py` auto-commit rejection:** check `state/dispatch_once.stderr.log` for the `auto-commit:` lines. `skipping AST validation` (interceptor/validator OK, P-UNB3 working) followed by `auto-commit FAILED: invalid syntax line 1` = a sidecar mis-route, not a validation-gate problem. Relates to [[rev26-exec-session]].
