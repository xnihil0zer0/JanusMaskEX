# Host CodeQL capability — verified for the Phase-III build

Read-only verification run during BUILD-PREP (no DB built — that is deferred to
the build's own Stage-2 leaves per the minutes/GB cost).

## Binary & version
- `codeql` present at `~/tools/codeql/codeql` (also on PATH).
- `codeql version` → **CodeQL command-line toolchain release 2.25.1** (2026).

## Query packs / suites (all resolve locally — offline-capable)
- `codeql resolve qlpacks` lists the bundled packs, incl.
  `codeql/python-queries (…/python-queries/1.7.11)`.
- The interprocedural security suite the cascade depends on resolves:
  `…/python-queries/1.7.11/codeql-suites/**python-security-extended.qls**`
  (+ its `security-extended-selectors.yml`). This suite ships the maintained
  UnsafeDeserialization / SSRF / PathInjection / CommandInjection / CodeInjection
  / SqlInjection taint queries — exactly the CWE distribution the corpus pays for.
- `codeql resolve languages` shows extractors for **python, javascript, java,
  go, cpp, csharp, ruby, …** — so the runner's `SECURITY_SUITES` (python/js/go/
  java) are all backed; the first build is Python-only (per DECISION §4.5).

## Implications for the build
- No `codeql pack download` is required at analyze time — the packs are already
  unpacked under `~/tools/codeql/qlpacks`, so DB-create + `database analyze` run
  fully **offline / jail-compatible** (DECISION §2a confirmed on this host).
- The 12 bundled custom specs in `data/ngv2/taint_specs/` (incl. the 5 CWE-502
  deser queries + manifest.json) are present and validated by the already-green
  `taint_spec_library`; `codeql_orchestrate` runs them alongside the suite.
- The `resolve qlpacks` "found in N same-priority locations" lines are the known
  deprecation-tool duplication notice for library packs, NOT a resolution error
  — `python-queries` and the security-extended suite resolve to a single path.

## Deferred (correctly NOT done in BUILD-PREP)
- Building a CodeQL database of any repo (minutes, ~GB) — owned by Stage-2 leaf
  B2 / the live driver D1 smoke run, gated behind the Stage-1 prefilter + the
  codeql_preflight license token.
