---
interfaces: "edits pyproject.toml in the external NobleGreedv2 repo to add a [tool.pytest.ini_options] table pinning testpaths = [\"tests\"], so bare `pytest` from the repo root collects ONLY the tests/ tree instead of walking the whole repo (corpus/target fixtures and unbuilt *_wired.py oracles) and emitting ~190 ModuleNotFoundError collection errors — making the NGv2 suite scope unambiguous and reproducible"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

pyproject.toml — pin pytest `testpaths = ["tests"]` via a new `[tool.pytest.ini_options]` table so bare `pytest` from the NGv2 repo root collects only the tests/ tree (no corpus/target walking, no ~190 ModuleNotFoundError collection errors)

# Scope

EDIT the EXISTING file pyproject.toml in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DEFECT (verified live 2026-06-11): pyproject.toml declares `[build-system]`, `[project]`, and `[tool.setuptools]` but NO `[tool.pytest.ini_options]` table, so pytest has no configured collection root. Bare `pytest` from root walks the entire tree (corpus/target fixtures and unbuilt `*_wired.py` oracles), producing ~190 ModuleNotFoundError collection errors.

THE FIX (config_schema — a pure declarative-manifest edit, NO code change): rewrite pyproject.toml so its FINAL content is EXACTLY the existing content with a single new `[tool.pytest.ini_options]` table appended after `[tool.setuptools]`, byte-for-byte as shown below, with a trailing newline after the last line and nothing else (no comments, no extra blank lines, no extra keys):

    [build-system]
    requires = ["setuptools"]
    build-backend = "setuptools.build_meta"

    [project]
    name = "ngv2"
    version = "0.0.0"
    requires-python = ">=3.10"

    [tool.setuptools]
    packages = ["ngv2"]

    [tool.pytest.ini_options]
    testpaths = ["tests"]

The only change is the trailing `[tool.pytest.ini_options]` table with the single key `testpaths = ["tests"]` (a one-element array). Every pre-existing line is retained verbatim, in order. Read the read-only staged target at `{WORK_DIR}/inbox/targets/pyproject.toml` FIRST to confirm the current content. Verify GREEN with `python -m pytest tests/ngv2/test_pytest_testpaths_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

DISPATCH DIRECTIVE — MANIFEST FORMAT (non-Python target — the harness's `_requires_verbatim_manifest` routes any non-`.py` files_touched to the verbatim whole-file `__JANUSMASK_MANIFEST__` apply path; a `__JANUSMASK_PATCHES__` symbol patch CANNOT apply to a non-Python file): emit a single top-level `__JANUSMASK_MANIFEST__` dict with EXACTLY ONE entry whose key is `'pyproject.toml'` and whose value is the VERBATIM whole-file final content. Reproduce the value with NO leading indentation on each TOML line — the table headers like `[build-system]` must start at column 0. The submission file MUST contain ONLY this `__JANUSMASK_MANIFEST__` assignment at top level (no other statements, no imports, no decorators). The value is WHOLE-FILE content — not a diff, not a fragment, not an appended tail. POST-EMIT SELF-CHECK (mandatory): your emitted manifest value must, when parsed by `tomllib`, yield `data["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]`; it must retain the `[build-system]`, `[project]`, and `[tool.setuptools]` tables unchanged; and it must add no key other than `testpaths`.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2-pytest-testpaths`. meta_task_type=`config_schema` (a declarative non-Python config/manifest edit on an external NGv2 target — fuzzer-bypassed and smoke-gate-skipped per META_TASK_POLICY; the diff-fuzzer cannot operate on a non-Python file and there is no Python surface to smoke). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["pyproject.toml"]` ONLY. Emission semantics: a single `__JANUSMASK_MANIFEST__` dict with EXACTLY ONE `'pyproject.toml'` entry carrying the verbatim whole-file content (per the DISPATCH DIRECTIVE — never a `__JANUSMASK_PATCHES__` list, never a symbol patch, never a diff/fragment). The DISPATCH DIRECTIVE — MANIFEST FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest tests/ngv2/test_pytest_testpaths_wired.py -q`. The committed RED oracle tests/ngv2/test_pytest_testpaths_wired.py is the authoritative acceptance contract — make it GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_pytest_ini_options_table_present`, `test_testpaths_pinned_to_tests`, `test_tests_is_only_collection_root_wired`).

# Non-Goals

This is an EDIT of one declarative file and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this change is verified solely by the committed unit oracle tests/ngv2/test_pytest_testpaths_wired.py. Do NOT author or modify any test — that oracle is committed and authoritative. Do NOT touch ANY `.py` file — no module, no test, no conftest, nothing. Do NOT modify, reorder, or remove any pre-existing line of pyproject.toml (`[build-system]`, `[project]`, `[tool.setuptools]` stay verbatim). Do NOT add any pytest ini key other than `testpaths` — no `addopts`, no `python_files`, no `markers`, no `pythonpath`. Do NOT set testpaths to anything other than the single-element `["tests"]`. Do NOT create pytest.ini, tox.ini, setup.cfg, conftest.py, or any other config file. PATCH-SHAPE non-goals: do NOT emit a `__JANUSMASK_PATCHES__` list or any symbol/region patch (pyproject.toml is not Python — the symbol-patch apply path cannot touch it); the edit rides ONLY as the single-entry verbatim `__JANUSMASK_MANIFEST__` whole-file dict. No network, no wall-clock, no randomness, no new dependencies.

# Inputs

The committed authoritative oracle at tests/ngv2/test_pytest_testpaths_wired.py (currently RED: 3 failed / 2 passed). It derives the repo root from its own file path (never CWD), parses pyproject.toml with stdlib `tomllib`, and asserts: (a) `test_pyproject_file_exists_at_repo_root` and `test_pyproject_parses_as_toml` (GREEN today, structural guards); (b) `test_pytest_ini_options_table_present` — a `[tool.pytest.ini_options]` table exists (RED today, KeyError 'pytest'); (c) `test_testpaths_pinned_to_tests` — `data["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]` (RED today); and (d) the wiring anchor `test_tests_is_only_collection_root_wired` — `testpaths` is exactly the single-element `["tests"]`, i.e. `tests` is the SOLE configured collection root (RED today). All three RED cases flip GREEN once the `[tool.pytest.ini_options]\ntestpaths = ["tests"]` stanza lands; nothing else satisfies the exact-value and single-root cases.

The EXACT current defective file content being replaced (pyproject.toml at HEAD):

    [build-system]
    requires = ["setuptools"]
    build-backend = "setuptools.build_meta"

    [project]
    name = "ngv2"
    version = "0.0.0"
    requires-python = ">=3.10"

    [tool.setuptools]
    packages = ["ngv2"]

The EXACT corrected whole-file content (reproduce VERBATIM as the manifest value — existing content plus the trailing pytest table, trailing newline):

    [build-system]
    requires = ["setuptools"]
    build-backend = "setuptools.build_meta"

    [project]
    name = "ngv2"
    version = "0.0.0"
    requires-python = ">=3.10"

    [tool.setuptools]
    packages = ["ngv2"]

    [tool.pytest.ini_options]
    testpaths = ["tests"]

# Deliverables

Edited pyproject.toml in the NobleGreedv2 repo whose entire content is the pre-existing `[build-system]`/`[project]`/`[tool.setuptools]` tables retained verbatim followed by a new `[tool.pytest.ini_options]` table with `testpaths = ["tests"]` — with NO change to any other file — so bare `pytest` from the NGv2 repo root collects only the tests/ tree and the ~190 ModuleNotFoundError collection errors from corpus/target/unbuilt-oracle walking are eliminated. Verified GREEN by `python -m pytest tests/ngv2/test_pytest_testpaths_wired.py -q` (all 5 cases, including the single-collection-root wiring anchor).
