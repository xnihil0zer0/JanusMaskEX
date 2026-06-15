---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "Restore EXACT original public contracts broken by two accepted live_bounty leaves: novelty_corpus.load_known_corpus(path=None) optional-arg signature, and the five pre-existing VULN_PATTERNS catalog entries byte-for-byte (keeping the new insecure_deserialization entry)."
---

# Title

Restore backward-compatible contracts regressed by the live_bounty epic leaves T-novelty and T-deser-wire

# Scope

Two small corrective EDITs to already-landed files; the failing pre-existing tests ARE the committed RED oracles.

(1) EDIT `ngv2/novelty_corpus.py`: the T-novelty leaf changed public signatures. Restore them EXACTLY while KEEPING the new CWE-population behavior (classify_title): `corpus_from_submissions_map(data: Any) -> List[dict]` (parameter name `data`, accepts any object, returns [] for non-dict) and `load_known_corpus(path: Optional[PathLike] = None) -> List[dict]` (parameter name `path`, OPTIONAL with default None meaning DEFAULT_CORPUS_PATH; missing/unparseable file returns []). The currently-failing oracle `tests/test_novelty_corpus_wired.py::test_default_path_points_at_real_data_file` (calls `load_known_corpus()` with no args) plus the whole of tests/test_novelty_corpus_wired.py and tests/test_novelty_corpus_cwe.py must ALL pass (union).

(2) EDIT `ngv2/pattern_scanner.py`: the T-deser-wire leaf paraphrased the five pre-existing VULN_PATTERNS entries (changed regexes/languages/descriptions), breaking `tests/ngv2/test_targets_scanner_wired.py` for hardcoded_secret and sql_injection. Replace the entire `VULN_PATTERNS` assignment with EXACTLY this statement (verbatim, including the kept insecure_deserialization entry — do not reformat, re-quote, or re-word ANY part):

```python
VULN_PATTERNS: Dict[str, Dict[str, object]] = {'sql_injection': {'pattern': '(?:execute(?:many)?|executescript)\\s*\\(.*(?:%|\\.format\\b|\\+)', 'severity': 'high', 'cwe': 'CWE-89', 'owasp': 'A03:2021-Injection', 'languages': ['python', 'javascript', 'typescript', 'java', 'php'], 'description': 'Possible SQL injection via string formatting in a query call.'}, 'command_injection': {'pattern': '(?:os\\.system|subprocess\\.(?:call|run|Popen|check_output)|popen)\\s*\\(', 'severity': 'critical', 'cwe': 'CWE-78', 'owasp': 'A03:2021-Injection', 'languages': ['python', 'ruby', 'php', 'javascript', 'typescript'], 'description': 'Possible OS command injection via a shell/process call.'}, 'eval_usage': {'pattern': '\\beval\\s*\\(', 'severity': 'high', 'cwe': 'CWE-95', 'owasp': 'A03:2021-Injection', 'languages': ['python', 'javascript', 'typescript', 'php', 'ruby'], 'description': 'Use of eval() can execute arbitrary code.'}, 'weak_crypto': {'pattern': '(?i)\\b(?:md5|sha1|des|rc4)\\b', 'severity': 'medium', 'cwe': 'CWE-327', 'owasp': 'A02:2021-Cryptographic Failures', 'languages': ['python', 'javascript', 'typescript', 'java', 'php'], 'description': 'Use of a weak or broken cryptographic algorithm.'}, 'hardcoded_secret': {'pattern': '(?i)\\b(?:password|passwd|secret|api[_-]?key|token)\\b\\s*[:=]\\s*[\'\\"][^\'\\"]+[\'\\"]', 'severity': 'high', 'cwe': 'CWE-798', 'owasp': 'A07:2021-Identification and Authentication Failures', 'languages': ['python', 'javascript', 'typescript', 'java', 'go', 'ruby', 'php', 'csharp'], 'description': 'Possible hardcoded credential assigned to a string literal.'}, 'insecure_deserialization': {'pattern': '\\b(?:pickle|cPickle|_pickle|marshal|joblib)\\.(?:loads|load)\\s*\\(|\\byaml\\.(?:unsafe_load|full_load|load)\\s*\\(|\\btorch\\.load\\s*\\(', 'severity': 'critical', 'cwe': 'CWE-502', 'owasp': 'A08:2021-Software and Data Integrity Failures', 'languages': ['python'], 'description': 'Insecure deserialization of untrusted data via pickle/marshal/yaml.load/torch.load/joblib'}}
```

REQUIRED PLAN SHAPE (the plan validator HARD-REJECTS drafts violating ANY of these):
- Exactly 2 tasks: (R-novelty-sig) EDIT of `ngv2/novelty_corpus.py`; (R-catalog-restore) EDIT of `ngv2/pattern_scanner.py`. Unique task_ids, never `T1`. Priority `critical` on both.
- EVERY task carries ALL top-level fields: task_id, title, meta_task_type, priority (lowercase), dependencies, files_touched, acceptance_criteria, spec_author, estimated_complexity, verification_command.
- EVERY task's test_spec lists >=2 edge_cases AND mirrors each of them in regression_tests or property_tests.
- EVERY task's spec non_goals MUST repeat the literal word "integration" — OR include an integration_test.
- verification_command is CWD-relative pytest, NO `cd` prefix. Use exactly: R-novelty-sig -> `python -m pytest tests/test_novelty_corpus_wired.py tests/test_novelty_corpus_cwe.py -q`; R-catalog-restore -> `python -m pytest tests/ngv2/test_targets_scanner_wired.py tests/test_deser_catalog_wired.py tests/test_pattern_scanner.py -q`.
- Do NOT add test_authoring tasks: ALL oracles are already committed and currently RED on live HEAD.
- MECHANISM for R-catalog-restore: this is a PARTIAL-EDIT dispatch — emit __JANUSMASK_PATCHES__ with EXACTLY ONE entry of kind 'symbol', name 'VULN_PATTERNS', whose code is the single assignment statement given verbatim above (the harness admits a top-level single-name assignment as the patch primary). Touch nothing else in the file.
- MECHANISM for R-novelty-sig: symbol patches of the two functions `corpus_from_submissions_map` and `load_known_corpus` only; keep the classify_title import/wiring intact.

# Non-Goals

integration. Both children are EDITs; per this section they carry the literal word integration so each EDIT leaf may reference it to excuse the integration-test requirement (each task must repeat "integration" in its own non_goals). Do NOT change detection behavior beyond restoring the original five entries verbatim; do NOT touch the insecure_deserialization entry, scan_file, scan_directory, LANG_EXTENSIONS, _COMPILED, or deser_detect.py. Do NOT remove the CWE-population behavior from novelty_corpus (tests/test_novelty_corpus_cwe.py must stay green). Do NOT auto-submit anything. No new files, no new tests.

# Inputs

Live NGv2 HEAD (master). Failing committed oracles on live HEAD: tests/test_novelty_corpus_wired.py::test_default_path_points_at_real_data_file (TypeError: load_known_corpus() missing 1 required positional argument); tests/ngv2/test_targets_scanner_wired.py::test_target_scans_as_exactly_its_pattern[hardcoded_secret-CWE-798] and [sql_injection-CWE-89] (0 findings — paraphrased regexes no longer match the fixtures). Green oracles that MUST STAY green: tests/test_novelty_corpus_cwe.py, tests/test_deser_catalog_wired.py, tests/test_pattern_scanner.py. The pre-regression file content is recoverable via `git show 3855007^:ngv2/pattern_scanner.py` (read-only reference).

# Deliverables

`ngv2/novelty_corpus.py` with the original public signatures restored (optional `path=None` default) AND cwe population kept; `ngv2/pattern_scanner.py` whose VULN_PATTERNS is byte-identical to the statement given in Scope. All named oracle files pass in union; the full NGv2 gate regains the three currently-failing tests without losing any currently-green ones.
