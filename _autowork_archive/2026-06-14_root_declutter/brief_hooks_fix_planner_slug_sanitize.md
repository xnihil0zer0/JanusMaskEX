---
interfaces: "in-place EDIT of harness/planner/cli.py — inside _finalize_epic_children, sanitize the child slug of path separators / '..' immediately after the existing strip()+'_'->'-' canonicalization and BEFORE the slug is used for dedup or returned (it later flows into (repo_root / ('brief_hooks_'+slug+'.md')).write_text at _run_epic_pipeline ~cli.py:210). Add two function-LOCAL imports (`import os`, `import re`); restrict the canonical to os.path.basename + the safe charset [A-Za-z0-9_-] (stripping leading/trailing dots), and `continue` (drop the child, as for a falsy slug) when sanitization empties it. NO signature change; NO other line of _finalize_epic_children changes; the dedup / working_dir-stamp / epic-mark behavior is byte-identical for benign slugs."
---

# Title

Sanitize epic child-brief slugs of path separators / '..' in _finalize_epic_children before they reach the filesystem (harness/planner/cli.py EDIT — harness_self_fix, CWE-22/CWE-20)

# Scope

EDIT `harness/planner/cli.py` (SENSITIVE path under `harness/**` — meta_task_type MUST be `harness_self_fix`; the operator decision file `state/control/decisions/fix-planner-slug-sanitize.json` authorizes the commit).

THE BUG (CWE-22 path traversal / CWE-20 improper input validation; found AND verified 2026-06-11): `_finalize_epic_children` canonicalizes each reconciled child-brief slug with ONLY `str(slug).strip().replace('_', '-')` (harness/planner/cli.py:154 at HEAD) and never strips `/` or `..`. The slug originates from LLM-reconciled child briefs (`run_reconciliation(..., mode='epic')` -> `recon.merged_tasks`), so it is UNTRUSTED input. The canonical slug then flows into a filesystem path at `_run_epic_pipeline` (harness/planner/cli.py:210): `(repo_root / ('brief_hooks_' + child['slug'] + '.md')).write_text(serialize_child_brief_to_markdown(child), encoding='utf-8')`. Because separators survive, a crafted slug lexically escapes repo_root: with `repo_root = /home/xnihil0zer0/JanusMaskJR`, a slug `a/../../x` produces `(repo_root / 'brief_hooks_a/../../x.md').resolve()` == `/home/xnihil0zer0/x.md` — OUTSIDE repo_root (VERIFIED via the real `_finalize_epic_children`). A slug `foo/bar` writes into a subdirectory (`brief_hooks_foo/bar.md`). The constant `brief_hooks_` prefix absorbs the first traversal segment and `write_text` does not create intermediate dirs, so the most naive `../../etc/x` payloads fail closed by accident (FileNotFoundError) — this is an input-validation / path-traversal HARDENING gap, not a clean RCE — but `a/../../x` demonstrably escapes repo_root, and a correct sanitizer would neutralize all of these. SEVERITY: moderate (untrusted-input -> filesystem-path with a confirmed lexical repo_root escape; partially mitigated today by the constant prefix + no-mkdir fail-closed behavior).

THE CURRENT vulnerable canonicalization (harness/planner/cli.py, inside `_finalize_epic_children`, the top of the `for child in merged:` loop, lines 150-154 at HEAD) is, byte-for-byte:

```python
    for child in merged:
        slug = child.get('slug')
        if not slug:
            continue
        canonical = str(slug).strip().replace('_', '-')
```

THE FIX (verified-diff: built in a /tmp clean worktree 2026-06-11 and proven the RED oracle goes 9/9 GREEN with the planner epic-pipeline regression tests still green): insert a slug-sanitization step immediately AFTER the existing `canonical = ...` line and BEFORE the `if canonical in seen:` dedup check, adding two function-LOCAL imports (`import os`, `import re`) — a function-local import keeps the change to the SINGLE symbol `_finalize_epic_children` (`os`/`re` are NOT imported at module top, and a module-top import would require a second, separate patch and is NOT wanted). The sanitizer strips directory components (`os.path.basename`), restricts to the safe charset `[A-Za-z0-9_-]`, drops leading/trailing dots, and `continue`s (drops the child exactly like a falsy slug) when sanitization empties the slug:

```python
    for child in merged:
        slug = child.get('slug')
        if not slug:
            continue
        canonical = str(slug).strip().replace('_', '-')
        # SANITIZE (CWE-22/CWE-20): the canonical slug flows into a filesystem
        # path (brief_hooks_<slug>.md) at _run_epic_pipeline; strip directory
        # components and restrict to a safe charset so an untrusted reconciled
        # slug cannot inject a path separator or '..' that escapes repo_root.
        import os
        import re
        canonical = os.path.basename(canonical)
        canonical = re.sub(r'[^A-Za-z0-9_-]', '', canonical).strip('.')
        if not canonical:
            continue
```

For a benign slug the sanitizer is a no-op beyond the documented strip()/'_'->'-' behavior: `spine_token_roi` -> `spine-token-roi`, `  alpha-one  ` -> `alpha-one`, `analytics-and-roi` -> `analytics-and-roi` (the `-` and alnum chars all survive the charset filter; basename of a separator-free string is itself). Malicious slugs are neutralized: `../../evil` -> `evil`, `a/../../x` -> `x`, `foo/bar` -> `bar`, `..` -> `''` (dropped). The subsequent exact-canonical dedup, near-synonym token-set dedup (`canonical.split('-')`), working_dir stamping, and epic-marking are all byte-identical and operate on the now-safe canonical — VERIFIED the 4-pair near-synonym collapse and the `alpha_one`/`alpha-one` exact-canonical collapse are unchanged.

LOUD DISPATCH DIRECTIVE — PATCH FORMAT (`harness/planner/cli.py` is a LARGE file; this MUST be a partial edit): emit a single top-level `__JANUSMASK_PATCHES__` list with EXACTLY ONE entry, kind `'symbol'`, name `'_finalize_epic_children'`, whose `code` is the FULL `def _finalize_epic_children(merged, epic_wd, child_epics):` reproduced BYTE-FOR-BYTE from the read-only staged target at `{WORK_DIR}/inbox/targets/harness/planner/cli.py`, changing ONLY the slug-canonicalization block shown above (insert the two function-local imports + the basename/charset sanitizer + the `if not canonical: continue` drop, immediately after the existing `canonical = str(slug).strip().replace('_', '-')` line). `_finalize_epic_children` spans lines 126-171 at HEAD (~46 lines). KNOWN GOTCHA — SYMBOL TRUNCATION: agents have deterministically truncated symbol reproductions before. POST-EMIT SELF-CHECK (mandatory): your emitted `_finalize_epic_children` must START with `def _finalize_epic_children(merged, epic_wd, child_epics):` and END with `    return finalized`, and must still contain the full docstring, the `_STOPWORDS = frozenset({` literal, the near-synonym `child_tokens` subset/superset dedup block, the `new_child = dict(child)` line, the `working_dir` stamp, and the `if child_epics:` mark — all byte-identical except the one inserted sanitization block. If your draft dropped any of those, you truncated — re-read the staged target and re-emit. Do NOT add a module-top `import os`/`import re`, do NOT emit a `__JANUSMASK_MANIFEST__`, do NOT emit a whole-file rewrite, do NOT add any new top-level symbol (no R-anchor — the change is wholly inside `_finalize_epic_children` via two function-local imports), do NOT touch `_run_epic_pipeline`, `_should_run_epic`, `persist_plan`, or any other symbol.

INV9 capability gate: the staged symbol `_finalize_epic_children` builds/sanitizes a STRING; the fix introduces only `os.path.basename`, `re.sub`, and `str.strip` — it contains NO `eval`/`exec`/`os.system`/`subprocess(..., shell=True)` Call node, so the staged symbol is capability-clean.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file is keyed to it): `task_id`: `fix-planner-slug-sanitize`. meta_task_type=`harness_self_fix`. priority: high. dependencies: []. SELF task (no `working_dir` — this edits JM itself). files_touched: `["harness/planner/cli.py"]` ONLY. partial_edit semantics (single `__JANUSMASK_PATCHES__` list with ONE `'symbol'` entry for `_finalize_epic_children`, per the LOUD DISPATCH DIRECTIVE). verification_command: `python -m pytest tests/test_planner_slug_sanitize_wired.py tests/planner/test_epic_child_subset_dedup.py tests/planner/test_epic_pipeline_dedup_childepics.py tests/planner/test_epic_pipeline_first_light.py tests/planner/test_epic_pipeline_working_dir.py -q`. The pre-authored RED oracle `tests/test_planner_slug_sanitize_wired.py` is the authoritative contract — make it 9/9 green; do NOT author new tests. The four `tests/planner/test_epic_*.py` paths are the pre-existing drift guards (17/17 green at HEAD) that exercise `_finalize_epic_children` and epic child-brief generation and must stay green.

REQUIRED: at least TWO `edge_cases` in `test_spec`, mirrored into `regression_tests` (and/or `property_tests`) — name exactly these two:
  1. a child slug carrying a path-escape payload (`a/../../x`) is sanitized so the canonical slug contains NO `/` and NO `..` component, and `(repo_root / ('brief_hooks_'+canonical+'.md')).resolve()` stays within `repo_root.resolve()`.
  2. a benign slug (`spine_token_roi`) still canonicalizes to exactly `spine-token-roi` (the documented strip()/'_'->'-' behavior is preserved; no behavioral change for legitimate inputs), and the existing exact-canonical / near-synonym dedup is unchanged.
A third (`foo/bar` -> single safe token; `..` -> dropped) MAY be included. `minimum_test_count` must be >= 1.5 × functional_requirements.

# Non-Goals

- Does NOT change `_finalize_epic_children`'s signature, its docstring, the `_STOPWORDS` set, the exact-canonical dedup, the near-synonym token-set dedup, the `working_dir` stamping, the `epic`-marking, or any other line of the function — ONLY the slug-canonicalization block (two function-local imports + basename/charset sanitizer + the `if not canonical: continue` drop).
- Does NOT add a module-top `import os` or `import re` (the function-local imports keep the change to one symbol); does NOT touch any other symbol in `harness/planner/cli.py`.
- Does NOT modify the write site `_run_epic_pipeline` (~cli.py:210), `serialize_child_brief_to_markdown`, the reconciliation pipeline, or any caller — only the slug-canonicalization is hardened; the write itself stays as-is and is rendered safe because the slug it receives is already sanitized.
- Does NOT touch any file other than `harness/planner/cli.py`.
- Out of scope: integration testing of the end-to-end epic decomposition / daemon child-brief promotion flow beyond the five listed pytest files; this leaf is a behavior-only unit fix verified by the pre-authored oracle plus the existing planner epic-pipeline regression tests. Broader repo_root path-confinement of OTHER write sites is a related follow-up tracked separately.

# Inputs

- Authoritative contract: the pre-authored RED oracle `tests/test_planner_slug_sanitize_wired.py`. Confirmed RED 2026-06-11: 5 failed (separator/`..` survives canonicalization for `../../evil`, `a/../../x`, `foo/bar`, `..`; and `a/../../x` escapes repo_root) / 4 passed (benign regression + the prefix-absorbed traversals that fail closed). After the fix it is 9/9 GREEN.
- Drift guards (pre-existing, all green at HEAD): `tests/planner/test_epic_child_subset_dedup.py` (imports and exercises `_finalize_epic_children` directly), `tests/planner/test_epic_pipeline_dedup_childepics.py`, `tests/planner/test_epic_pipeline_first_light.py`, `tests/planner/test_epic_pipeline_working_dir.py` — 17/17 at HEAD; must stay green (catch any faithful-reproduction drift in the 46-line `_finalize_epic_children` and confirm benign canonicalization/dedup/working_dir behavior is unchanged).
- VERIFIED DIFF (2026-06-11, /tmp clean-worktree build): with ONLY the slug-canonicalization block changed (two function-local imports + `os.path.basename` + `re.sub(r'[^A-Za-z0-9_-]', '', canonical).strip('.')` + `if not canonical: continue`), the RED oracle is 9/9 GREEN and the planner epic-pipeline regression set stays green; the INV9 capability gate passes (the function builds/sanitizes a STRING; it contains no `subprocess(..., shell=True)`/eval/exec/os.system Call node, so the staged symbol is capability-clean).
- The verbatim CURRENT canonicalization block and its exact corrected form are embedded in `# Scope`; the staged read-only target is at `{WORK_DIR}/inbox/targets/harness/planner/cli.py` (`_finalize_epic_children` spans lines 126-171 at HEAD).

# Deliverables

`harness/planner/cli.py` with `_finalize_epic_children`'s slug-canonicalization block changed to add two function-local imports (`import os`, `import re`) and sanitize the canonical slug (`os.path.basename` + restrict to `[A-Za-z0-9_-]` + drop leading/trailing dots + drop the child when sanitization empties it), so an untrusted reconciled child slug can no longer inject a path separator or `..` that escapes repo_root when written as `brief_hooks_<slug>.md`. Turns `tests/test_planner_slug_sanitize_wired.py` 9/9 GREEN while the four `tests/planner/test_epic_*.py` drift guards stay green (17/17). Every other line of `_finalize_epic_children` and of `harness/planner/cli.py` is byte-identical; benign child-slug canonicalization, dedup, working_dir stamping, and epic-marking are unchanged in behavior.
