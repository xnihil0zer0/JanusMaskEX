---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - targets-dir-convention-oracle
  - targets-dir-convention-impl
interfaces: >
  Root-cause hardening: the harness has NO designated targets directory, so a target referenced
  by a BARE NAME or a REPO-ROOT-RELATIVE path in a brief's `working_dir` resolves CWD-relative
  (= the repo root, since the daemon runs there) and gets cloned/bootstrapped INTO the repo tree,
  polluting agent search with ~18.6k third-party files. The 7 existing clones were relocated to
  `~/NobleGreedv2/targets/` (owner-approved); this brief makes that relocation a PERMANENT,
  REUSABLE convention so any future target lands OUTSIDE the repo automatically.

  SEAM (verified by reading the code): `harness/target_bootstrap.py::bootstrap_target(working_dir)`
  is the SINGLE front door for every external target (called from the daemon at
  `harness/autowork_daemon.py:1679` after `_target_is_self()` says not-self; it already
  `Path(working_dir).resolve()`-es at line 297 and is the gate before any external work). It is
  NOT trust-core (NOT in `_NEVER_AUTO_APPROVE`, orchestrator.py:2424), so `harness_self_fix`
  auto-approve is eligible. We add a NEW pure resolver helper there,
  `resolve_target_path(working_dir, config=None) -> Path`, that maps a BARE NAME / repo-root-
  relative target to `<targets_dir>/<name>` (default `~/NobleGreedv2/targets`, `~`-expanded) and
  leaves an already-absolute external path UNCHANGED, then have `bootstrap_target` call it FIRST
  so resolution happens before the existing `.resolve()` + allowlist + marker checks.

  SINGLE-TREE SCOPE (critical for auto-approve): this impl edits EXACTLY ONE file,
  `harness/target_bootstrap.py` (a `harness/**` path). The default targets_dir is shipped as a
  MODULE CONSTANT in that file (NO new `config/**` file is created), because the sensitive
  auto-approve gate (`orchestrator._auto_approve_sensitive_eligible`) REJECTS a `config/**` rel
  riding along with a `harness/**` change (only `tests/**`/docs ride along) -> a config file would
  fail-closed to `auto_commit_failed`. The resolver reads configuration ONLY from a passed-in
  `config` dict (when present and containing a truthy string `targets_dir`); otherwise it falls
  back to the module constant. There is NO config file, NO file read, NO config path of any kind.

  WHY this seam (NOT paths.py): the central `effective_target_root()`/`_target_is_self()` live in
  `harness/paths.py`, which IS trust-core AND is deliberately `Path.home()`-free for clone
  portability (paths.py:53-54) — it cannot expand `~`. `target_bootstrap.py` is non-trust-core and
  already does `.expanduser()`-style home access (precedent: selfheal.py:157/164-166), so it is the
  correct host for the `~`-expansion of the resolved `targets_dir`.

  DEFAULT-SAFE / BACKWARD-COMPAT: resolution is a NO-OP for (a) an already-absolute external
  `working_dir` (honored unchanged), and (b) self-targeted flows (harness self-fix), which never
  reach `bootstrap_target` (the daemon's `_target_is_self()` guard short-circuits first). Only a
  BARE NAME or a repo-root-relative target string is rewritten under `targets_dir`.
---

# Title
targets_dir convention: resolve bare/relative target names under `~/NobleGreedv2/targets` (outside the repo), not repo-root-relative

# Scope
ONE file, ONE behavior, ONE implementation task (READ it first):

`harness/target_bootstrap.py` — EDIT this SINGLE EXISTING module (READ the whole file; it is
~325 lines). Add a NEW pure helper + a default constant and wire it into `bootstrap_target`.
Do NOT create any other file. Specifically:

   a. Add a module-level constant for the default and a NEW helper:
      ```
      _DEFAULT_TARGETS_DIR = '~/NobleGreedv2/targets'

      def _read_targets_dir(config=None) -> Path:
          """Resolve the configured targets_dir, ~-expanded, absolute.

          ONLY config source: a truthy string `targets_dir` in the passed
          `config` dict (after .strip()); otherwise _DEFAULT_TARGETS_DIR.
          Returns Path(raw).expanduser().resolve() — always absolute, ~-expanded,
          ~-free. NO file read, no config-path constant, no parser import;
          a tiny pure dict-or-constant lookup. Empty/whitespace/falsey -> default.
          """
          ...

      def resolve_target_path(working_dir, config=None) -> Path:
          """Map a target reference to its on-disk location.

          - An ALREADY-ABSOLUTE path is returned resolved, UNCHANGED (backward-compat).
          - A BARE NAME (no path separator) or a relative path resolves under
            _read_targets_dir(config): <targets_dir>/<name>, OUTSIDE the repo tree.
          Returns an absolute Path. Pure (no filesystem mutation, no git)."""
          ...
      ```
   b. In `bootstrap_target(working_dir)`, call `resolve_target_path(working_dir)` to produce the
      effective root BEFORE the existing `root = Path(working_dir).resolve()` line (currently
      `harness/target_bootstrap.py:297`). Concretely, change line 297 from
      `root = Path(working_dir).resolve()` to `root = resolve_target_path(working_dir).resolve()`.
      Everything downstream of that line (the `_working_dir_allowed` gate, marker/ownership checks,
      git init, venv, marker write) MUST stay byte-for-byte unchanged.

Implementation guidance (exec-free, statically analyzable Python — NO exec/eval/compile/__import__,
they are AST-banned per harness/ast_enforcer.py:71):
- `~`-expansion: use `Path(raw).expanduser()`. This is ALLOWED here (target_bootstrap.py is
  non-trust-core and already accesses HOME via the jail; selfheal.py:157/164-166 is the precedent).
  Do NOT add `expanduser`/`Path.home()` to harness/paths.py — that module is deliberately home-free.
- Config source (dict-only, NO file read): inside `_read_targets_dir`, if `config` is a dict AND
  `config.get('targets_dir')` is a truthy string after `.strip()`, use that value as `raw`;
  otherwise `raw = _DEFAULT_TARGETS_DIR`. Then `return Path(raw).expanduser().resolve()`. The
  function is a tiny pure dict-or-constant lookup: NO file read, NO file open, NO config path
  literal, NO try/except for parse errors. The ONLY artifact you ship is the single
  `harness/target_bootstrap.py` file, and the ONLY config source is the passed `config` dict.
- "Bare name vs relative vs absolute" classification: treat `Path(working_dir).is_absolute()` as
  the ABSOLUTE case (return `Path(working_dir).resolve()` unchanged). Otherwise (bare name OR
  relative), return `(_read_targets_dir(config) / working_dir).resolve()` — note a bare `fastgpt`
  becomes `<targets_dir>/fastgpt`, and a relative `foo/bar` becomes `<targets_dir>/foo/bar`. Do
  NOT special-case `.`/`..` traversal beyond what `.resolve()` already normalizes (the existing
  `_working_dir_allowed` deny-all allowlist remains the authoritative safety gate downstream).
- `resolve_target_path` MUST be PURE: no `mkdir`, no git, no marker writes — it only computes a
  Path. All mutation stays in the existing `bootstrap_target` body, unchanged.
- Preserve the existing module docstring, all imports, and EVERY existing function
  (`_git`, `_marker_path`, `_read_valid_marker`, `_working_dir_allowed`, `_has_git`, `_is_dirty`,
  `external_staging_root`, `_ensure_*`, `_resolve_target_interpreter`, `_external_venv_dir`,
  `_jailed_install_argv`, `_write_marker`) byte-for-byte unchanged except the single line 297 edit.

This is `harness_self_fix` editing EXACTLY ONE `harness/**` file. `harness/target_bootstrap.py` is
NOT in `_NEVER_AUTO_APPROVE` (orchestrator.py:2424), and the change is a SINGLE `harness/**` rel
(no `config/**`/`scripts/**` rel riding along), so `_auto_approve_sensitive_eligible` PASSES and
auto-approve is eligible with NO operator decision file.

# Inputs
READ `harness/target_bootstrap.py` in full (especially `bootstrap_target` at ~:289-325, the
`root = Path(working_dir).resolve()` line at **:297**, the lazy `from harness.paths import STATE_DIR`
pattern at :93/:229, and the module docstring at :1-36). READ `harness/paths.py` to confirm
that `effective_target_root`/`_target_is_self` (:73-187) already classify an absolute external
path correctly (so once `bootstrap_target` resolves to an absolute external path, the rest of the
pipeline is unchanged). Note the relocated clones live at
`~/NobleGreedv2/targets/{fastgpt,flowise,graphiti,h4_guildai,mem0,one-api,w2d_modeldb}` (verified
present).

Existing tests that MUST still pass (no-regression — do NOT break them): any
`tests/**/test_target_bootstrap*.py` and `tests/**/test_*bootstrap*.py` exercising
`bootstrap_target` / `_working_dir_allowed`.

# Non-Goals
Integration is out of scope for this implementation task (the literal word `integration` is here to
excuse the integration-test requirement on a `.py`-editing task). Do NOT create ANY `config/**`
file — and do NOT read one either; the targets_dir comes ONLY from the passed `config` dict or the
`_DEFAULT_TARGETS_DIR` module constant (a `config/**` rel riding along with a `harness/**` change
fails the auto-approve gate -> auto_commit_failed). Do NOT edit `harness/paths.py` (trust-core AND home-free by
design) — resolution lives in `target_bootstrap.py`. Do NOT add `expanduser`/`Path.home()` to
paths.py. Do NOT change `effective_target_root`, `_target_is_self`, `brief_loader.py`, or
`planner/cli.py::_effective_repo_root`. Do NOT auto-CLONE targets (cloning stays a manual operator
step per _phase_prep/phase4/RUN_PLAN.md — this brief only RESOLVES a path). Do NOT weaken or bypass
the `_working_dir_allowed` deny-all allowlist gate. Do NOT use exec/eval/compile/__import__
(AST-banned). Do NOT mutate the filesystem inside `resolve_target_path` (it MUST be pure). Do NOT
change behavior for an already-absolute external `working_dir` (must be byte-identical) or for
self-targeted flows. Do NOT author tests beyond the one paired oracle. Do NOT create any module
other than `harness/target_bootstrap.py`.

# Deliverables
- `harness/target_bootstrap.py` with `_DEFAULT_TARGETS_DIR = '~/NobleGreedv2/targets'`,
  `_read_targets_dir(config=None)` (reading `targets_dir` ONLY from the passed `config` dict, else
  the constant — NO file read), and `resolve_target_path(working_dir, config=None)` added, and
  `bootstrap_target` line 297 changed to resolve through `resolve_target_path`. A bare-name target
  resolves to `<targets_dir>/<name>` OUTSIDE the repo; an absolute external path is byte-identical
  to today. NO config file is created or read.
- GREEN under the scoped verification_command; no regression in existing target_bootstrap tests.

# Required plan shape
Emit EXACTLY ONE `test_authoring` task and EXACTLY ONE `harness_self_fix` implementation task that
depends on it (so the single RED oracle is NOT dropped).

## Task 1 (oracle)
- task_id MUST be exactly `targets-dir-convention-oracle`.
- meta_task_type: test_authoring
- files_touched: ["tests/harness/test_targets_dir_convention.py"]
- OMIT mutation_target.
- non_goals MUST contain the literal word `integration`.
- verification_command:
  `python -m pytest tests/harness/test_targets_dir_convention.py -q`

The oracle file `tests/harness/test_targets_dir_convention.py` MUST import
`from harness.paths import PROJECT_ROOT` (used by the outside-repo assertion) and
`from harness.target_bootstrap import resolve_target_path, _read_targets_dir`, and define a
module-level `_EXPECTED_DEFAULT = Path('~/NobleGreedv2/targets').expanduser().resolve()`. It MUST
assert ALL of (it is RED today because the symbols do not exist yet). There is NO config file and
NO config-path monkeypatching anywhere — with no file read, `_read_targets_dir()`
with no config deterministically returns `_EXPECTED_DEFAULT`. Exactly 10 test functions:
  1. **Bare name -> targets_dir (config dict) + outside-repo:** with `targets_dir` set to a tmp dir
     via a passed `config` (`{'targets_dir': str(tmp)}`), `resolve_target_path('fastgpt',
     config={...})` returns `(tmp / 'fastgpt').resolve()` and is OUTSIDE the repo tree (assert
     `PROJECT_ROOT` is NOT a parent of the result).
  2. **Default targets_dir (~-expansion):** with NO config, `_read_targets_dir()` returns
     `_EXPECTED_DEFAULT` (an absolute path with no literal `~`), and `resolve_target_path('mem0')`
     lands under it.
  3. **Absolute external path unchanged (backward-compat):** for an absolute path OUTSIDE both the
     repo and targets_dir (e.g. `tmp_path / 'somewhere_else'`), `resolve_target_path(<that abs>)`
     returns `Path(<that abs>).resolve()` UNCHANGED (NOT rewritten under targets_dir, never joined).
  4. **Relative multi-segment path -> nests under targets_dir:** `resolve_target_path('sub/dir',
     config={'targets_dir': str(tmp)})` returns `(tmp / 'sub' / 'dir').resolve()`.
  5. **Purity (no mkdir):** calling `resolve_target_path('newname', config={'targets_dir':
     str(tmp)})` does NOT create `<tmp>/newname` on disk (assert `not (tmp / 'newname').exists()`
     afterward).
  6. **Fail-safe (empty config falls back to default):** `_read_targets_dir(config={'targets_dir':
     ''})` (empty/falsey) returns `_EXPECTED_DEFAULT` (NOT an empty path).
  7. **Resolver never mutates fs (property):** over a few sample inputs (bare name, relative,
     absolute), calling `resolve_target_path` creates no new filesystem entries under a `tmp_path`
     targets_dir.
  8. **`_read_targets_dir` always absolute + ~-free (property):** for each config in
     `[None, {}, {'targets_dir': ''}, {'targets_dir': '   '}, {'targets_dir': str(valid)}]`
     (where `valid` is a `tmp_path` subdir), the result `.is_absolute()` is True and `'~'` is not
     in `str(result)` (the first four yield `_EXPECTED_DEFAULT`; the last yields `valid.resolve()`).
  9. **Real targets dir never touched (hermetic):** the whole suite runs without creating or
     reading `~/NobleGreedv2/targets` (no monkeypatch needed now; assert default resolution does not
     require the dir to exist).
  10. **Oracle never invokes bootstrap_target:** a guard test asserting the suite exercises only the
     pure resolver + config reader and never calls `bootstrap_target` (which would run git/venv).

The oracle MUST be hermetic: use `tmp_path` only, never touch the real `~/NobleGreedv2/targets`,
and never invoke `bootstrap_target`. Test ONLY the pure resolver + config reader. No `monkeypatch`
is needed for any test (there is no file read to redirect). minimum_test_count: 9 (10 surviving
tests satisfy >=9).

## Task 2 (impl)
- task_id MUST be exactly `targets-dir-convention-impl`.
- meta_task_type: harness_self_fix
- depends_on: ["targets-dir-convention-oracle"]
- files_touched: ["harness/target_bootstrap.py"]
- mutation_target: harness.target_bootstrap   (MODULE dotted path ONLY — never module.function)
- non_goals MUST contain the literal word `integration`; regression_tests >= 2.
- ⚠️ MANIFEST KEYS — READ CAREFULLY (a prior attempt FAILED here three times with
  `manifest_undeclared_key`): the `__JANUSMASK_MANIFEST__` dict MUST contain **EXACTLY ONE key**,
  the literal string `'harness/target_bootstrap.py'`, mapped to the FULL module contents (the
  complete module with the three additions above). It MUST NOT contain ANY other key — an
  extra/undeclared manifest key triggers `manifest_undeclared_key` and the task is rejected. There
  is NO config file: the synthesized module MUST NOT reference any config-file path literal, any
  config-directory constant, or any YAML parser import ANYWHERE — no config file, no config path
  literal, no parser import. The ONLY config source is the passed `config` dict; otherwise the
  `_DEFAULT_TARGETS_DIR` constant. Whole-file (NOT `__JANUSMASK_PATCHES__`) because it introduces
  NEW top-level symbols. spec_author: null (the oracle is pre-committed via the test_authoring task).
- verification_command:
  `python -m pytest tests/harness/test_targets_dir_convention.py -q`
