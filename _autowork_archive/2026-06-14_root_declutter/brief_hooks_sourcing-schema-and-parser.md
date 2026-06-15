---
interfaces: "build_eligible_cache(repos: list[str], fetched_at: str) -> dict; build_repo_bounties(repo_records: dict) -> dict; build_existing_submissions(submission_records: dict) -> dict; write_snapshots(data_dir: str, eligible: dict, bounties: dict, submissions: dict) -> None; parse_hacktivity(html: str) -> list[dict]; parse_repo_page(html: str) -> dict; parse_bounties_index(html: str) -> list[str]"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Pure huntr snapshot schema builders/writers + RSC-flight page parser (Part A, Level 0)

# Scope

Build the two pure, dependency-free Level-0 sourcing leaves that everything else in Part A composes over. (1) `ngv2/sourcing/huntr_snapshot_schema.py`: pure builders that assemble the EXACT three snapshot JSON shapes the existing `huntr_cache_loader` already reads, plus deterministic (sorted-key, stable-ordering) writers to a target data dir. The three shapes are: `huntr_eligible_cache.json` = {"repos": [sorted "owner/repo" strings], "fetched_at": "<iso8601 UTC>"}; `huntr_repo_bounties.json` = {"repos": {"owner/repo": {eligible, tier, observed_payouts:{critical,high,medium,low}, max_paid, total_advisories, submissions, pool_note}}}; `huntr_existing_submissions.json` = {"owner/repo": {"status": int, "count": int, "titles": [str,...]}}. (2) `ngv2/sourcing/huntr_page_parser.py`: a pure React-Server-Component (RSC) "flight" payload extractor over INJECTED HTML strings (no network) for the hacktivity feed (id, title, createdAt, patch_commit_sha, status, cve_id, cvss, cwe{id,description}, repository{owner,name,language}, disclosure{amount}, maintainer triage) and per-repo pages (full disclosure set + maintainer accept/reject rationale `#score|0|awarded`, `#self_closedduplicate`, free-text rejections). Ensure `ngv2/sourcing/__init__.py` exists. Each leaf ships a `test_<module>_wired.py` oracle importing the live `ngv2.sourcing.<module>`, with the schema oracle round-tripping its output through the unchanged loaders, ≥2 edge_cases each, and a CWD-relative `verification_command` (no `cd` prefix).


REQUIRED PLAN SHAPE (the plan validator HARD-REJECTS drafts violating ANY of these):
- Exactly 2 tasks: (T-schema) NEW single-file module `ngv2/sourcing/huntr_snapshot_schema.py`; (T-parser) NEW single-file module `ngv2/sourcing/huntr_page_parser.py`. Unique task_ids, never `T1`. `ngv2/sourcing/__init__.py` already exists — do not create or edit it.
- EVERY task carries ALL top-level fields: task_id, title, meta_task_type, priority (lowercase one of critical/high/medium/low), dependencies, files_touched, acceptance_criteria, spec_author, estimated_complexity, verification_command.
- EVERY task's test_spec lists >=2 edge_cases AND mirrors each of them in regression_tests or property_tests entries.
- EVERY task's spec non_goals MUST repeat the literal word "integration" — OR include an integration_test.
- verification_command is CWD-relative pytest, NO `cd` prefix anywhere. Use exactly: T-schema -> `python -m pytest tests/test_huntr_snapshot_schema_wired.py -q`; T-parser -> `python -m pytest tests/test_huntr_page_parser_wired.py -q`.
- Do NOT add test_authoring tasks: the RED oracles are ALREADY COMMITTED to the target repo master (commit 7f14c23: tests/test_huntr_snapshot_schema_wired.py, tests/test_huntr_page_parser_wired.py). Those oracle files ARE the binding contract — implement exactly their asserted signatures and semantics. The parser oracle (extended in commit 7f9811c) requires: (a) BOTH input forms — HTML-wrapped `self.__next_f.push([1,"<id>:<json>\n"])` chunks AND bare raw RSC flight streams (rows `<id>:<json>\n`, including length-prefixed text rows `<id>:T<hexlen>,<raw>` whose payload may contain newlines, so naive line-splitting mis-frames; scan-decode or honor the T-length framing); (b) `parse_bounties_index(html) -> list[str]` extracting sorted, de-duplicated, LOWERCASED "owner/name" strings from server-rendered `/bounties` index anchors `href="...?target=https://github.com/{owner}/{name}"`; (c) the REAL captured payload fixtures under tests/fixtures/huntr/ (hacktivity >=80 full records incl. kedro CVE-2026-3840; bentoml repo page >=30 disclosures with `#score|0|awarded` rationale preserved; real index >=120 repos) must pass — these are large (170-430KB) so the implementation must be reasonably efficient (no catastrophic regex backtracking).

# Non-Goals

Do NOT perform any network I/O or browser automation here — parsing is pure over injected HTML/record fixtures only; the live fetcher belongs to a sibling. Do NOT modify `huntr_cache_loader.py`, `huntr_data.py`, `check_eligible`, or any downstream consumer — the schema's only contract is producing byte-shapes those unchanged loaders accept. Do NOT retrofit or import the inert `ngv2/sourcing/huntr_client.py`. Do NOT write any learning/analytics, selection, or fetch-policy logic. Do NOT commit any `data/ngv2/*.json` runtime artifacts.

# Inputs

Existing untouched loaders this child's output must satisfy: `ngv2/huntr_cache_loader.py` (`load_cache`, `load_repo_bounties`, `load_existing_submissions`; `_DEFAULT_DATA_DIR = <ngv2>/../data/ngv2`), `ngv2/huntr_data.py::parse_bounties`/`parse_existing_submissions`, `ngv2/huntr_eligible_cache.py::check_eligible`. Seam/style reference: `ngv2/sourcing/huntr_client.py` injected-`Fetcher` style and `ngv2/contracts.py` `Bounty`/`Target` dataclasses (`to_dict`/`from_dict`/`validate`). Sample real fixtures to mirror shapes: `data/ngv2/huntr_existing_submissions.json`, `data/ngv2/huntr_repo_bounties.json`, `data/ngv2/huntr_eligible_cache.json`.

# Deliverables

`ngv2/sourcing/huntr_snapshot_schema.py` exposing: `build_eligible_cache(repos: list[str], fetched_at: str) -> dict`, `build_repo_bounties(repo_records: dict) -> dict`, `build_existing_submissions(submission_records: dict) -> dict`, and deterministic writer `write_snapshots(data_dir: str, eligible: dict, bounties: dict, submissions: dict) -> None` (sorted keys, stable ordering, the three exact filenames). `ngv2/sourcing/huntr_page_parser.py` exposing: `parse_hacktivity(html: str) -> list[dict]` and `parse_repo_page(html: str) -> dict` (pure RSC-flight extraction over injected HTML). Plus `ngv2/sourcing/__init__.py`.
