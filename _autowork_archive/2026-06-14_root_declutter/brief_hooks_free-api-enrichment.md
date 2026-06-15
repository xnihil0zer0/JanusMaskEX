---
dependencies:
  - "sourcing-schema-and-parser"
interfaces: "query_osv(fetcher, package: str | None = None, cve: str | None = None) -> list[dict]; parse_osv(body: str) -> list[dict]; fetch_ghsa(fetcher, ecosystem: str = 'pip') -> list[dict]; parse_ghsa(body: str) -> list[dict]; records join huntr on cve_id/ghsa_id and merge into build_repo_bounties(repo_records: dict) -> dict shape"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

OSV.dev and GitHub Security Advisory fetchers merged into the snapshot schema (Part B, Level 3, optional)

# Scope

Build the free-clean-API enrichment fetchers that follow the same injected-seam producer pattern and merge into the snapshot schema, joined to huntr records on `cve_id`/`ghsa_id`. (1) `ngv2/sourcing/osv_fetcher.py`: pure-parse over an injected fetcher for OSV.dev (`POST https://api.osv.dev/v1/query`, no auth) carrying CWE/CVSS/fix-commit. (2) `ngv2/sourcing/ghsa_fetcher.py`: pure-parse over an injected fetcher for GitHub Security Advisories (`GET https://api.github.com/advisories?ecosystem=pip`, using the already-authenticated `gh` token, 5000 req/hr) carrying CWE/CVSS/fix-commit and `vulnerable_functions[]` (a direct reachability signal). Both parse pure over injected responses and emit records mergeable into the `huntr_repo_bounties` schema shape. Each leaf ships a `test_<module>_wired.py` oracle importing live `ngv2.sourcing.<module>` with a stub fetcher (offline), ≥2 edge_cases, CWD-relative `verification_command` (no `cd`).


REQUIRED PLAN SHAPE (the plan validator HARD-REJECTS drafts violating ANY of these):
- Exactly 2 tasks: (T-osv) NEW single-file `ngv2/sourcing/osv_fetcher.py`; (T-ghsa) NEW single-file `ngv2/sourcing/ghsa_fetcher.py`. Unique task_ids, never `T1`.
- EVERY task carries ALL top-level fields: task_id, title, meta_task_type, priority (lowercase one of critical/high/medium/low), dependencies, files_touched, acceptance_criteria, spec_author, estimated_complexity, verification_command.
- EVERY task's test_spec lists >=2 edge_cases AND mirrors each of them in regression_tests or property_tests entries.
- EVERY task's spec non_goals MUST repeat the literal word "integration" — OR include an integration_test.
- verification_command is CWD-relative pytest, NO `cd` prefix anywhere. Use exactly: T-osv -> `python -m pytest tests/test_osv_fetcher_wired.py -q`; T-ghsa -> `python -m pytest tests/test_ghsa_fetcher_wired.py -q`.
- Do NOT add test_authoring tasks: the RED oracles are ALREADY COMMITTED to the target repo master (tests/test_osv_fetcher_wired.py, tests/test_ghsa_fetcher_wired.py). Those oracle files ARE the binding contract — implement exactly their asserted signatures and semantics.

# Non-Goals

Do NOT perform real network I/O in oracles — inject stub fetchers and stay hermetic. NEVER auto-submit anything. Do NOT add HackerOne or Bugcrowd scrapers (deferred). Do NOT re-derive the snapshot JSON shapes; consume the sibling's builders. Do NOT commit `data/ngv2/*.json` runtime artifacts. Do NOT modify downstream selection/loader contracts. No bulk-harvesting violating robots/ToS; polite rate-limited, incremental fetching only.

# Inputs

From sibling `sourcing_schema_and_parser`: `build_repo_bounties(repo_records: dict) -> dict` (the merge target shape) and the snapshot-writer contract. Seam style: `ngv2/sourcing/huntr_client.py` `Fetcher = Callable[[url, headers], (status, body, headers)]`. Join keys: huntr records' `cve_id` / `ghsa_id`.

# Deliverables

`ngv2/sourcing/osv_fetcher.py` exposing `query_osv(fetcher, package: str | None = None, cve: str | None = None) -> list[dict]` and a pure `parse_osv(body: str) -> list[dict]`. `ngv2/sourcing/ghsa_fetcher.py` exposing `fetch_ghsa(fetcher, ecosystem: str = 'pip') -> list[dict]` and a pure `parse_ghsa(body: str) -> list[dict]` (records include CWE, CVSS, fix-commit, `vulnerable_functions`). Both produce records joinable to huntr on `cve_id`/`ghsa_id` and mergeable into the `build_repo_bounties` shape.
