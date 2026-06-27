# I_codeql — CodeQL taint-reachability lead source for NGv2

External target: `/home/xnihil0zer0/NobleGreedv2` @ HEAD `205d30c` (verified via
throwaway worktree at `/tmp/ngv2_codeql_wt`, now removed; the real tree was
NEVER touched — read-only / scratch-only as required).

## Goal
Make CodeQL the PRIMARY hunt lead source so findings entering triage/poc are
interprocedural-taint REACHABILITY-VERIFIED, instead of regex-syntactic sinks
that die at the `sink_reachability` / `poc_authenticity` gates.

## files_touched
- `ngv2/codeql_lead_source.py`  — NEW module (the bridge + lead source)
- `ngv2/hunt_lead_client.py`    — WIRED CodeQL as the first lead source
- `tests/ngv2/test_codeql_lead_source.py` — NEW hermetic oracle (resolves under
  `tests/ngv2/` in this repo's layout; the scratch copy is named
  `test_codeql_lead_source.py`)
- `tests/ngv2/fixture_cmdinj.sarif` — real `py/command-line-injection` SARIF
  fixture (copy of `/tmp/cqlsmoke/_out.sarif`)

## New module: ngv2/codeql_lead_source.py (stdlib-only, deterministic, fail-soft)
Public API:
- `codeql_scan(repo_path, *, db_root='tmp/codeql', codeql_bin=None,
  languages=None, runner=None, query_suite=None, timeout=900) -> List[dict]`
- `findings_to_candidates(findings, target) -> List[dict]`
- helpers: `detect_languages`, `detect_codeql_bin`, `codeql_available`

`codeql_scan`:
- Auto-detects languages (`python` if any `.py`; `javascript` if any
  `.js/.jsx/.ts/.tsx/.mjs/.cjs`) unless `languages=` given; deterministic order
  python-before-js; skips `.git/.venv/node_modules/...`.
- Auto-detects codeql bin: arg > env `NGV2_CODEQL_BIN` >
  `/home/xnihil0zer0/tools/codeql/codeql` > `shutil.which('codeql')`.
- Reuses `codeql_runner.create_database` to build the DB and constructs argv for
  the security-extended suite (`SECURITY_SUITES[language]`). Uses the injected
  `runner` for tests, else `codeql_runner.make_subprocess_runner(bin, timeout=)`.
- Captures the RAW SARIF (via a small local `_run_analyze_raw`, NOT a change to
  codeql_runner) so it can recover the taint source location, then parses with
  `codeql_runner.parse_sarif` for the sink rows.
- Enriches each finding (`_enrich`): normalize CWE, read sink snippet, infer
  sink_name, extract taint source, `reachable=True`, `source='codeql'`.
- FAIL-SOFT: bad repo / no langs / no bin / subprocess or parse error → `[]`
  (never raises); a per-finding enrichment error keeps a best-effort record.

`findings_to_candidates`:
- Reuses `hunt_lead_client._normalize_candidate` (lazy import) so output is
  byte-identical to the agy/regex candidate shapes, then re-asserts the codeql
  flags. Importable without invoking codeql (no module-scope subprocess).

### SARIF → candidate mapping
| candidate key            | source                                                            |
|--------------------------|-------------------------------------------------------------------|
| `category`               | `parse_sarif` `cwe` (e.g. `['CWE-078','CWE-088']`) → `_normalize_cwe` → primary, zero-pad stripped → `'CWE-78'` |
| `call_sites`             | sink code line read from `<repo>/<file>` at `line` (+1 ctx line)  |
| `sink_name`              | `sink_extract.extract_sink(snippet)`; else `_RULE_SINK_HINTS[rule_id]` (e.g. `py/command-line-injection`→`subprocess.Popen`) |
| `evidence`               | `["<file>:<line>"]` (the SINK location)                           |
| `severity`/`description` | from parsed finding (`message` fallback)                          |
| `reachable`/`codeql_reachable` | `True` (set on every codeql candidate)                     |
| `source`                 | `'codeql'`                                                        |
| `source_location`/`entrypoint` | taint SOURCE location (see below)                           |
| `id`,`target`,`expected_fs_signature`,`success_marker` | from `_normalize_candidate` |

### Source-location extraction (what parse_sarif DROPS)
`_extract_source_location(result)` reads the raw SARIF result:
1. first `codeFlows[].threadFlows[].locations[0].location.physicalLocation`
   (the taint ENTRY point — for the fixture: `app/vuln.py:2`), else
2. first `relatedLocations[].physicalLocation` with a region.
Returns `{'file','line'}`, carried as `source_location` and folded into an
`entrypoint` string (`file:line`) to help poc grounding. `parse_sarif` is
unchanged (returns sink-only); the extractor lives in the NEW module per spec.

## Wiring (hunt_lead_client.py)
Order of preference: **CodeQL → agy → regex-fallback**.

In `lead_client`, immediately after computing `repo`/`target` and BEFORE the agy
`try:` block, inserted:

OLD:
```python
        repo = ctx.get('repo') or pool.get('repo') or ''
        target = pool.get('target') or pool.get('subject') or ctx.get('target') or repo
        try:
            messages = _build_messages(repo, target)
```
NEW:
```python
        repo = ctx.get('repo') or pool.get('repo') or ''
        target = pool.get('target') or pool.get('subject') or ctx.get('target') or repo
        # PRIMARY lead source: CodeQL interprocedural taint ... (comment)
        codeql_cands = _codeql_leads(repo, target)
        if codeql_cands:
            return {'candidates': codeql_cands}
        try:
            messages = _build_messages(repo, target)
```

Added two module-level helpers next to the existing `pattern_scanner`/
`sink_extract` imports (so the lazy `codeql_lead_source` import mirrors how
`sink_extract`/`sink_localize` are guarded):
- `_codeql_enabled()` — env-flag + binary check.
- `_codeql_leads(repo, target)` — fail-soft runner: returns `[]` (caller falls
  through unchanged) on disable/no-repo/no-bin/any error; else
  `codeql_scan(repo)` → `findings_to_candidates`.

`codeql_runner.py` public API: UNCHANGED. `lead_client.backend == 'agy'`:
PRESERVED.

### Env-flag behavior (`NGV2_CODEQL_LEADS`)
- unset / any value not in the disable-set → ENABLED **iff** a codeql binary
  auto-detects (so machines without codeql, and existing tests, are undisturbed).
- `'0' | 'false' | 'no' | 'off'` (case-insensitive) → DISABLED → straight to agy.

## RED → GREEN evidence
- RED: with the new module removed and `hunt_lead_client.py` reverted to HEAD,
  `tests/ngv2/test_codeql_lead_source.py` errors at collection
  (`ModuleNotFoundError: No module named 'ngv2.codeql_lead_source'`).
- GREEN: with the module + wiring in place, `10 passed`.

Test coverage (hermetic — scripted runner feeds the saved fixture, NO real
codeql binary):
- (a) cmd-injection SARIF → candidate: `category=='CWE-78'`, sink-line
  `call_sites` containing `subprocess.Popen`, `sink_name` set, `reachable True`,
  `source=='codeql'`, `evidence==['app/vuln.py:9']`, `source_location` from
  codeFlows (`app/vuln.py:2`), agy-shape hints defaulted.
- (b) candidate passes `sink_reachability_gate.assess_sink_reachability` →
  `reachable=True, may_confirm=True`.
- (c) determinism across 2 runs (findings + candidates equal).
- (d) fail-soft: raising runner → `[]`; non-dict SARIF → `[]`; missing repo →
  `[]`; `findings_to_candidates(None/str)` → `[]`.
- (e) wiring: codeql present → preferred over agy (`source=='codeql'`,
  `category=='CWE-78'` not agy's `CWE-89`); `NGV2_CODEQL_LEADS=0` → falls back to
  agy; codeql empty → falls back to agy.

## Regression
`python -m pytest -q -k "hunt or lead or codeql or sink or triage or pattern or campaign"`:
**397 passed, 16 failed** — ALL 16 failures are the pre-existing
`tests/ngv2/test_z3_solver_adapter_wired.py::test_grounding_differential_matches_rule_fallback[...]`
family. Confirmed pre-existing: reverting my changes to pristine HEAD and running
that file alone reproduces the same failures (`25 failed, 3 passed` for the whole
z3 file; the `-k` selector only collected 16 of them). My change introduces ZERO
new failures. (Note: memory said "8-failure family"; the actual z3 file fails
broader at this HEAD — `25` total in the file, `16` under the `-k` selector — but
none are mine.)

Named anti-regression oracles, run explicitly — all GREEN (40 passed):
`tests/ngv2/test_hunt_fallback.py`, `tests/ngv2/test_hunt_lead_client.py`,
`tests/ngv2/test_codeql_runner.py`, `tests/ngv2/test_sink_localization.py`.

## NOT hermetically verifiable (owner must run with the real codeql binary)
- Real `codeql database create --language=python --source-root=<repo>` +
  `codeql database analyze ... python-security-extended.qls --rerun` on a live
  NGv2 target repo. The subprocess path (`make_subprocess_runner` with the
  resolved bin) is exercised only via the scripted seam here; the actual DB
  build/analyze timing, suite resolution on disk, and real SARIF shape per
  target are unverified in this hermetic run.
- JavaScript-language end-to-end (detection is unit-tested; real js DB build is
  not). Detection + suite mapping for `javascript` exist
  (`SECURITY_SUITES['javascript']`).
- Whether real CodeQL findings on the live eligible repos actually yield
  CLAIMABLE PoCs downstream (this closes the lead-REACHABILITY gap; the poc
  template-coverage gap noted in memory is a separate blocker).

## How to land (owner)
The 4 files are in this scratch dir. Apply to NGv2 via the JM pipeline (NOT a
hand-edit): `ngv2/codeql_lead_source.py` is a NEW single-file module (whole-file)
+ `ngv2/hunt_lead_client.py` is an additive edit (2 helpers + a guarded
early-return) + commit the oracle `tests/ngv2/test_codeql_lead_source.py` and
`tests/ngv2/fixture_cmdinj.sarif` BEFORE the impl run.
