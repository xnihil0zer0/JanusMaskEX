---
dependencies:
  - "sourcing-schema-and-parser"
interfaces: "Fetcher = Callable[[str, dict], tuple[int, str, dict]]; fetch_hacktivity(fetcher: Fetcher) -> str; fetch_repo_page(fetcher: Fetcher, owner: str, name: str) -> str; fetch_bounties_index(fetcher: Fetcher) -> str; is_stale(fetched_at: str, now: str, max_age_hours: float) -> bool; next_delay(attempt: int, base_seconds: float) -> float; refresh(fetcher: Fetcher, data_dir: str, now: str) -> dict"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Injected live fetcher, refresh policy, and the wired huntr_refresh entrypoint (Part A, Levels 1-2)

# Scope

Build the runtime composition that turns the pure schema+parser foundation into fresh snapshots. (1) `ngv2/sourcing/browser_fetcher.py`: an injected live fetcher exposing the seam `Fetcher = Callable[[str, dict], tuple[int, str, dict]]` (status, body, response-headers), using an `RSC: 1` HTTP GET for bulk feeds and a Playwright path only for lazy-loaded per-disclosure detail bodies; tests inject a STUB fetcher and stay fully offline/hermetic. (2) `ngv2/sourcing/refresh_policy.py`: pure staleness + polite rate-limit/backoff logic over `fetched_at` (~1 req/sec, incremental by `published_at`). (3) `ngv2/sourcing/huntr_refresh.py`: the wired entrypoint composing fetch -> parse (via the parser) -> freshness/rate-limit policy -> write_snapshots (via the schema writer) into `_DEFAULT_DATA_DIR`. Its oracle injects a stub fetcher + tmp dir and asserts the three files land and the unchanged `load_cache` consumes them. Each leaf ships a `test_<module>_wired.py` oracle importing live `ngv2.sourcing.<module>`, ≥2 edge_cases, CWD-relative `verification_command` (no `cd`).


REQUIRED PLAN SHAPE (the plan validator HARD-REJECTS drafts violating ANY of these):
- Exactly 3 tasks: (T-fetcher) NEW single-file `ngv2/sourcing/browser_fetcher.py`; (T-policy) NEW single-file `ngv2/sourcing/refresh_policy.py`; (T-refresh) NEW single-file `ngv2/sourcing/huntr_refresh.py` depending on T-fetcher and T-policy. Unique task_ids, never `T1`.
- EVERY task carries ALL top-level fields: task_id, title, meta_task_type, priority (lowercase one of critical/high/medium/low), dependencies, files_touched, acceptance_criteria, spec_author, estimated_complexity, verification_command.
- EVERY task's test_spec lists >=2 edge_cases AND mirrors each of them in regression_tests or property_tests entries.
- EVERY task's spec non_goals MUST repeat the literal word "integration" — OR include an integration_test.
- verification_command is CWD-relative pytest, NO `cd` prefix anywhere. Use exactly: T-fetcher -> `python -m pytest tests/test_browser_fetcher_wired.py -q`; T-policy -> `python -m pytest tests/test_refresh_policy_wired.py -q`; T-refresh -> `python -m pytest tests/test_huntr_refresh_wired.py -q`.
- Do NOT add test_authoring tasks: the RED oracles are ALREADY COMMITTED to the target repo master (commits 81c632d + 7f9811c + 85fdd5b: tests/test_browser_fetcher_wired.py, tests/test_refresh_policy_wired.py, tests/test_huntr_refresh_wired.py). Those oracle files ARE the binding contract. NOTE: browser_fetcher must ALSO expose `fetch_bounties_index(fetcher: Fetcher) -> str` — a plain GET of https://huntr.com/bounties WITHOUT the RSC header (the index is server-rendered HTML, not flight); non-200 raises, like the other fetch helpers.
- T-refresh ELIGIBILITY SEMANTICS (pinned by the committed oracle, commit 85fdd5b): `refresh` derives the eligible-repo set ONLY from `fetch_bounties_index` -> `parse_bounties_index` (the /bounties index is the single eligibility authority); a repo seen in hacktivity but absent from the index is NOT eligible and `huntr_eligible_cache.json` must contain exactly the sorted index repos. The `RSC: 1` header goes ONLY on hacktivity//repos/ flight GETs, never on the index GET. A pre-existing snapshot whose `fetched_at` equals the injected `now` short-circuits with ZERO fetcher calls. Empty index/feed still writes the three loader-valid (empty) snapshot files. existing-submissions titles surface for ELIGIBLE repos from the hacktivity records.

# Non-Goals

NEVER auto-submit: no HTTP POST to huntr, no Playwright form-fill/click — findings are parked for a human only. Do NOT re-derive the JSON shapes or HTML parsing here; consume the sibling's schema builders/writers and page parser verbatim. Do NOT retrofit `ngv2/sourcing/huntr_client.py`. Do NOT commit `data/ngv2/*.json` — they are RUNTIME outputs of this entrypoint; only the code is a pipeline leaf. Do NOT perform real network I/O in oracles; always inject a stub fetcher. Do NOT build the learning/selection layer. No bulk-harvesting violating robots/ToS.

# Inputs

From sibling `sourcing-schema-and-parser`: `build_eligible_cache(repos: list[str], fetched_at: str) -> dict`, `build_repo_bounties(repo_records: dict) -> dict`, `build_existing_submissions(submission_records: dict) -> dict`, `write_snapshots(data_dir: str, eligible: dict, bounties: dict, submissions: dict) -> None`, `parse_hacktivity(html: str) -> list[dict]`, `parse_repo_page(html: str) -> dict`, `parse_bounties_index(html: str) -> list[str]` (sorted unique lowercased "owner/name" from the /bounties index HTML — the only eligibility authority). Existing untouched consumers the output must satisfy: `ngv2/huntr_cache_loader.py` (`load_cache`, `_DEFAULT_DATA_DIR = <ngv2>/../data/ngv2`). Seam style: `ngv2/sourcing/huntr_client.py` `Fetcher = Callable[[url, headers], (status, body, headers)]`; runner-injection style `ngv2/acquisition/cloner.py`. Legacy reference (read-only): `/home/xnihil0zer0/AI-Data/NobleGreed-legacy/services/rate_limiter.py` flock pattern.

# Deliverables

`ngv2/sourcing/browser_fetcher.py` exposing `Fetcher = Callable[[str, dict], tuple[int, str, dict]]`, `fetch_hacktivity(fetcher: Fetcher) -> str`, `fetch_repo_page(fetcher: Fetcher, owner: str, name: str) -> str`. `ngv2/sourcing/refresh_policy.py` exposing `is_stale(fetched_at: str, now: str, max_age_hours: float) -> bool` and `next_delay(attempt: int, base_seconds: float) -> float`. `ngv2/sourcing/huntr_refresh.py` exposing `refresh(fetcher: Fetcher, data_dir: str, now: str) -> dict` that fetches, parses, applies policy, and calls `write_snapshots` so the unchanged `load_cache` reads the result.
