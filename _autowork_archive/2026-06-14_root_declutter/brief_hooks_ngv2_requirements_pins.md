---
interfaces: "edits requirements.txt in the external NobleGreedv2 repo to add five dependency floor pins matching the wheels already installed in the NGv2 venv (verified live 2026-06-11: z3-solver 4.16.0.0, tree-sitter 0.25.2, tree-sitter-c 0.24.2, tree-sitter-java 0.23.5, tree-sitter-javascript 0.25.0) — retaining the existing pytest>=7 line — so a fresh `pip install -r requirements.txt` reproduces the runtime dependency set the NGv2 detonation/AST tooling actually imports, instead of silently omitting every non-pytest wheel"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

requirements.txt — pin the five already-installed runtime wheels (`z3-solver>=4.16`, `tree-sitter>=0.25`, `tree-sitter-c>=0.24`, `tree-sitter-java>=0.23`, `tree-sitter-javascript>=0.25`) alongside the retained `pytest>=7`, so the declared dependency manifest matches what the NGv2 venv actually runs

# Scope

EDIT the EXISTING file requirements.txt in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). DEFECT (verified live 2026-06-11): requirements.txt declares exactly ONE line — `pytest>=7` — yet the NGv2 venv has five additional wheels installed and load-bearing for the AST/solver tooling: z3-solver 4.16.0.0, tree-sitter 0.25.2, tree-sitter-c 0.24.2, tree-sitter-java 0.23.5, tree-sitter-javascript 0.25.0. A fresh environment built from requirements.txt would be missing all five.

THE FIX (config_schema — a pure declarative-manifest edit, NO code change): rewrite requirements.txt so its FINAL content is EXACTLY these six lines, in EXACTLY this order, byte-for-byte, with a trailing newline after the last line and nothing else (no comments, no blank lines, no extra whitespace):

    pytest>=7
    z3-solver>=4.16
    tree-sitter>=0.25
    tree-sitter-c>=0.24
    tree-sitter-java>=0.23
    tree-sitter-javascript>=0.25

The first line is the UNCHANGED existing `pytest>=7` (retain it verbatim — do not re-pin, re-floor, or reorder it); the five new lines are major.minor floor pins matching the installed venv versions. Read the read-only staged target at `{WORK_DIR}/inbox/targets/requirements.txt` FIRST to confirm the current single-line content. Verify GREEN with `python -m pytest tests/ngv2/test_requirements_pins_wired.py -q`; working_dir is /home/xnihil0zer0/NobleGreedv2.

DISPATCH DIRECTIVE — MANIFEST FORMAT (non-Python target — the harness's `_requires_verbatim_manifest` routes any non-`.py` files_touched to the verbatim whole-file `__JANUSMASK_MANIFEST__` apply path; a `__JANUSMASK_PATCHES__` symbol patch CANNOT apply to a non-Python file): emit a single top-level `__JANUSMASK_MANIFEST__` dict with EXACTLY ONE entry whose key is `'requirements.txt'` and whose value is the VERBATIM whole-file six-line final content:

    __JANUSMASK_MANIFEST__ = {
        'requirements.txt': r'''pytest>=7
z3-solver>=4.16
tree-sitter>=0.25
tree-sitter-c>=0.24
tree-sitter-java>=0.23
tree-sitter-javascript>=0.25
''',
    }

The submission file MUST contain ONLY this `__JANUSMASK_MANIFEST__` assignment at top level (no other statements, no imports, no decorators). The value is WHOLE-FILE content — not a diff, not a fragment, not an appended tail. Use a raw triple-quoted string exactly as shown. POST-EMIT SELF-CHECK (mandatory): your emitted manifest value must contain exactly SIX non-empty lines; line 1 must be `pytest>=7` unchanged; lines 2–6 must be `z3-solver>=4.16`, `tree-sitter>=0.25`, `tree-sitter-c>=0.24`, `tree-sitter-java>=0.23`, `tree-sitter-javascript>=0.25` in that order; the value must contain no `#` comment, no `==` exact pin, no version other than the floors shown, and no blank line.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2-requirements-pins`. meta_task_type=`config_schema` (a declarative non-Python config/manifest edit on an external NGv2 target — fuzzer-bypassed and smoke-gate-skipped per META_TASK_POLICY; the diff-fuzzer cannot operate on a non-Python file and there is no Python surface to smoke). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["requirements.txt"]` ONLY. Emission semantics: a single `__JANUSMASK_MANIFEST__` dict with EXACTLY ONE `'requirements.txt'` entry carrying the verbatim six-line whole-file content (per the DISPATCH DIRECTIVE — never a `__JANUSMASK_PATCHES__` list, never a symbol patch, never a diff/fragment). The DISPATCH DIRECTIVE — MANIFEST FORMAT paragraph above MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest tests/ngv2/test_requirements_pins_wired.py -q`. The committed RED oracle tests/ngv2/test_requirements_pins_wired.py (NGv2 commit 5b4b5f1) is the authoritative acceptance contract — make it GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle `tests/ngv2/test_requirements_pins_wired.py` (plan descriptors referencing committed/landed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_requirements_exact_six_line_content`, `test_pytest_floor_line_retained`, `test_z3_solver_pin_line_present`, `test_installed_versions_satisfy_pin_floors_wired`).

# Non-Goals

This is an EDIT of one declarative file and integration is out of scope: the task's non_goals MUST declare integration testing out of scope — do NOT add integration/e2e tests; this change is verified solely by the committed unit oracle tests/ngv2/test_requirements_pins_wired.py. Do NOT author or modify any test — that oracle is committed and authoritative. Do NOT touch ANY `.py` file — no module, no test, no conftest, nothing. Do NOT install or uninstall anything (no `pip install`, no `pip uninstall`, no venv mutation — the five wheels are ALREADY installed; this leaf only makes requirements.txt declare them). Do NOT modify the `pytest>=7` line (it stays line 1, verbatim). Do NOT reorder, remove, or add lines beyond the pinned six-line content — no comments, no blank lines, no `--hash`/`--index-url` options, no extras, no environment markers. Do NOT use `==` exact pins or any floor other than the major.minor floors pinned in Scope. Do NOT create requirements-dev.txt, setup.py, pyproject.toml, constraints.txt, or any other packaging file. PATCH-SHAPE non-goals: do NOT emit a `__JANUSMASK_PATCHES__` list or any symbol/region patch (requirements.txt is not Python — the symbol-patch apply path cannot touch it); the edit rides ONLY as the single-entry verbatim `__JANUSMASK_MANIFEST__` whole-file dict. No network, no wall-clock, no randomness, no new dependencies beyond the five declared pins.

# Inputs

The committed authoritative oracle at tests/ngv2/test_requirements_pins_wired.py (NGv2 commit 5b4b5f1; currently RED: 6 failed / 3 passed). It derives the repo root from its own file path (never CWD), reads requirements.txt, and asserts: (a) `test_pytest_floor_line_retained` — the existing `pytest>=7` line survives verbatim (GREEN today); (b) five per-package pin-line tests — `test_z3_solver_pin_line_present`, `test_tree_sitter_pin_line_present`, `test_tree_sitter_c_pin_line_present`, `test_tree_sitter_java_pin_line_present`, `test_tree_sitter_javascript_pin_line_present` — each asserting its pin line appears verbatim (all RED today); (c) `test_requirements_exact_six_line_content` — the file's non-empty stripped lines equal EXACTLY the six pinned lines in order (RED today); and (d) the wiring anchor `test_installed_versions_satisfy_pin_floors_wired` — `importlib.metadata.version(<package>)` for each of the five packages parses and its major/minor numerically satisfies the pin floor, stdlib-only, NO skipif (GREEN today, proving the pins match the live venv: z3-solver 4.16.0.0, tree-sitter 0.25.2, tree-sitter-c 0.24.2, tree-sitter-java 0.23.5, tree-sitter-javascript 0.25.0). All six RED cases flip GREEN once the six-line content lands; nothing else can satisfy the exact-content case.

The EXACT current defective file content being replaced (requirements.txt at HEAD — one line):

    pytest>=7

The EXACT corrected whole-file content (reproduce VERBATIM as the manifest value — six lines, this order, trailing newline):

    pytest>=7
    z3-solver>=4.16
    tree-sitter>=0.25
    tree-sitter-c>=0.24
    tree-sitter-java>=0.23
    tree-sitter-javascript>=0.25

# Deliverables

Edited requirements.txt in the NobleGreedv2 repo whose entire content is the six pinned lines exactly as specified in Scope — the retained `pytest>=7` followed by `z3-solver>=4.16`, `tree-sitter>=0.25`, `tree-sitter-c>=0.24`, `tree-sitter-java>=0.23`, `tree-sitter-javascript>=0.25` — with NO change to any other file, so the declared dependency manifest matches the wheels the NGv2 venv actually has installed and a fresh `pip install -r requirements.txt` reproduces the runtime dependency set. Verified GREEN by `python -m pytest tests/ngv2/test_requirements_pins_wired.py -q` (all 9 cases, including the importlib.metadata wiring anchor).
