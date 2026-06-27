---
name: ngv2-target-repo-commit-verification
description: "NGv2-target factory tasks commit to the NobleGreedv2 repo, not JanusMaskJR; verify auto_commit ledger rows against the task's working_dir repo, never assume JM."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d1161f3e-56af-47fe-ac54-6aed38730f04
---

🪝 OPERATIONAL GOTCHA (2026-06-25, I got this wrong — raised a false "false-LANDED" alarm).
JanusMask is the **factory**; the **code it builds lands in the TARGET repo**. For NGv2-closure
tasks the task `working_dir` = `/home/xnihil0zer0/NobleGreedv2`, so `_auto_commit_accepted`
(`harness/orchestrator.py:_auto_commit_accepted`) sets `worktree_root = effective_target_root(working_dir)`
(`harness/paths.py`), stages into an external clone (`external_staging_root()`,
`harness/target_bootstrap.py`), commits there, and fast-forward-integrates into **NGv2**. The
`auto_commit` ledger row, the brief-archive (`_autowork_archive/.../reconciled/`), and the
`state/tasks/processed/<id>.json` record ALL live on the **JM** (orchestration) side, while the
commit SHA lands in **NGv2**.

**Why:** I ran `git cat-file -e <commit_sha>` against JanusMaskJR, found it ABSENT + HEAD unmoved +
file missing, and wrongly concluded a silent false-LANDED auto_commit bug. An adversarial sub-agent
refuted it: the SHA was NGv2's HEAD all along (`git -C ~/NobleGreedv2 log` showed
"Integrate validated code for <task>"), the test was tracked + green, and a blast-radius scan of the
last 400 accepts found **0** absent from BOTH repos. No bug. `decode_check ok:False` after an
auto_commit is pure post-emission telemetry (`_decode_check_safe`, orchestrator_worker.py:257) — never
gates, never touches git; its `ok:False` is cosmetic.

**How to apply:** when triaging any `auto_commit` row, read the task's `working_dir` FIRST and run git
verification against THAT repo (`git -C /home/xnihil0zer0/NobleGreedv2 …` for NGv2-target tasks). JM-self
harness tasks (working_dir=JM) integrate into JM; NGv2 tasks integrate into NGv2. Don't conflate the
orchestration ledger (JM) with the target object store (NGv2). [[dont-conflate-built-with-works]]
[[never-claim-capability-works-without-empirical-proof]]
