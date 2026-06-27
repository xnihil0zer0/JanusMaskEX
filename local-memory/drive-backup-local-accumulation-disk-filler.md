---
name: drive-backup-local-accumulation-disk-filler
description: The JM drive_backup snapshots ~2.9G/commit to ~/.janusmask/drive_backup/artifacts and never prunes locally — the real disk filler (not logs/NGv2); policy = keep only most-recent-per-repo local after verified Drive upload
metadata: 
  node_type: memory
  type: project
  originSessionId: 5806b3a4-a81c-4bcd-bd94-332326f30802
---

💽 ROOT CAUSE of fast disk fill (found 2026-06-24, owner's disk hit 100%): `tools/drive_backup/hook_runner.py::run_backup` tars each repo's WORKING TREE to `~/.janusmask/drive_backup/artifacts/<Repo>_<sha>_<ts>.tar.zst` on EVERY commit/push, uploads to Google Drive (rclone), records `{"archive_name","uploaded":true}` in `~/.janusmask/drive_backup/ledger.ndjson` — but NEVER prunes the local copies. 118 snapshots ≈ 130G had accumulated. Each is ~2.9G because NGv2's working tree bundles vendored deps/venvs (`litellm-python` 22G, `.venv`, `tmp`) into the tar — so ~120 near-identical copies of the same vendoring. NOT logs (310M), NOT NGv2 source. The static ML collections (ComfyUI 479G, ~/.cache HF+pip ~179G, Documents 200G, lmstudio 51G, miniconda 78G) are the near-full BASELINE; drive_backup is the only FACTORY-driven grower (~5.8G per brief = 2 commits).

**Owner policy (2026-06-24):** Drive (~30TB free) holds full history; local keeps ONLY the most-recent snapshot per repo. Delete a local snapshot ONLY after its Drive upload is verified (`ledger uploaded==true`); fail-closed — never delete an un-uploaded/no-ledger-row copy.

**Reclaim recipe (operator, safe):** parse `ledger.ndjson` → set of `archive_name` with `uploaded==true`; keep newest `*.tar.zst` per repo-prefix; delete the rest (+ sibling `.diff`) only if in the uploaded set; `rm -rf ~/.cache/pip` (pure cache). Reclaimed 176G (99%→89%).

**Durable fix LANDED 2026-06-25 (wired + fail-closed verified; prune NOT YET observed firing):** brief `drive_backup_local_retention_one` added `_prune_local_snapshots(artifacts_dir, ledger_entries, keep=1)` called after `ledger.record(...)` in `run_backup` (hook_runner.py:164) — enforces local single-copy-per-repo, gated `uploaded is True` (fail-closed), keep-newest-per-repo, never touches Drive. Landed via the [[whole-file-drift-rootcause-and-patch-recipe]] `__JANUSMASK_PATCHES__` recipe (oracle b54b15b / impl 22e1131; 1 new symbol + 3 modified). ⚠️NOT YET DEMONSTRATED (adversarial audit 2026-06-25 REFUTED an earlier "demonstrated" claim): the prune code has provably NEVER run — last backup push 02:47 UTC predates impl commit 04:45 UTC, no push since; the current 1-snapshot-per-repo state is residue of the earlier MANUAL 176G reclaim, NOT the code. TO DEMONSTRATE: on the next real push, after a repo gets a 2nd commit the snapshot count must stay at 1 (prune deleted the older uploaded snapshot). Classic [[done-means-observed-working-not-a-green-gate]] trap. ⚠️Separate open follow-up: the ~2.9G snapshot bloat itself (exclude vendored venvs/deps or `git archive`) — not yet briefed.
