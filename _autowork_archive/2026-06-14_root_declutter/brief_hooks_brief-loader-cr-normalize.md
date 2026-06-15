---
interfaces: "load_brief(path, max_bytes) -> PlanningBrief — unchanged signature; content SHA-256 becomes invariant across \\n, \\r\\n, and bare \\r line endings"
---

# Title

Fix brief_loader line-ending normalization: a bare `\r` must hash like `\n` (harness/planner/brief_loader.py)

# Scope

Fix the CONFIRMED pre-existing bug (HANDOFF §1; failing Hypothesis property
`tests/planner/test_brief_loader.py::test_sha256_line_ending_invariant`, falsifying example
`text='0\r\r'`): `load_brief` in `harness/planner/brief_loader.py` normalizes line endings with
`normalized_text = raw_text.replace('\r\n', '\n')` (line 190), which collapses CRLF but leaves a
bare carriage return untouched, so the content SHA-256 computed on line 191 is NOT line-ending
invariant. The exact current code at the defect site is:

```python
    normalized_text = raw_text.replace('\r\n', '\n')
    sha256 = hashlib.sha256(normalized_text.encode('utf-8')).hexdigest()
```

The fix is the minimal one-line change inside `load_brief`:

```python
    normalized_text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
```

(`\r\n` must be collapsed FIRST so a CRLF does not become two newlines.) All downstream
frontmatter/section parsing already operates on `normalized_text`, so a fully `\r`-separated brief
also begins to parse correctly — that is intended and asserted by the oracle. No other line of the
function changes.

meta_task_type=`harness_self_fix` (sensitive `harness/planner/**`; operator decision file provided).
verification_command: `python -m pytest tests/planner/test_brief_loader_cr_normalize.py tests/planner/test_brief_loader_cr_normalize_wired.py -q`

# Required plan shape

ONE impl task; meta_task_type=`harness_self_fix`; files_touched=
`["harness/planner/brief_loader.py"]` (NO other paths — do not list test files or config). The
verification_command EXACTLY as above — it MUST name BOTH oracle files including the `..._wired.py`
token (the plan validator requires a `*_wired` oracle for any task editing a non-test `.py` file;
omitting it fails `missing_wiring_oracle`). Both oracles are PRE-COMMITTED and RED — their
docstrings/assertions are the authoritative contract; do NOT author tests. The task's
`spec.non_goals` MUST contain the literal word `integration` (e.g. "No integration test — exercised
by the existing planner pipeline") so the `missing_integration_test` check is excused — MANDATORY.
>=2 edge_cases mirrored in regression/property tests (e.g. (a) `\r\n` input still hashes identically
to `\n` — no double-newline from chained replace, (b) bare `\r` embedded mid-section hashes like
`\n`, (c) a fully `\r`-separated brief parses and hashes like its `\n` form). EMISSION: symbol
patches — re-emit the single existing top-level function `load_brief` with ONLY the one
normalization line changed. Do NOT emit whole-file or `__JANUSMASK_MANIFEST__`; do NOT add new
top-level symbols; touch exactly ONE symbol.

# Inputs

Pre-committed RED oracle `tests/planner/test_brief_loader_cr_normalize.py` (authoritative contract:
identical `.sha256` across `\n`/`\r\n`/bare-`\r` variants of the same content) and wiring oracle
`tests/planner/test_brief_loader_cr_normalize_wired.py`. The defect site is
`harness/planner/brief_loader.py:190` inside `load_brief` (function starts at `:160`). The existing
property test `tests/planner/test_brief_loader.py::test_sha256_line_ending_invariant` (currently
FAILING) goes green as a side effect.

# Non-Goals

Do NOT change `load_brief`'s signature, return type, error behavior, size limits, UTF-8 handling, or
any frontmatter/section parsing logic. Do NOT touch `_parse_frontmatter`, `_parse_markdown_sections`,
or any other symbol in the file. Do NOT relax the bare-section-heading strictness (separate, owner
decision). Do NOT author or modify tests (oracles pre-committed). No integration test — the change is
exercised by the existing planner pipeline; integration coverage exists in the brief_loader suite.

# Deliverables

EDIT `harness/planner/brief_loader.py`: the one-line chained-replace normalization inside
`load_brief`. Turns `tests/planner/test_brief_loader_cr_normalize.py` GREEN (and the pre-existing
failing property test in `tests/planner/test_brief_loader.py`) with zero regressions in the planner
suite.
