# Gap H — Taint-aware sink localization for the empty-hunt fallback

Target tree: `/home/xnihil0zer0/NobleGreedv2` @ `ef15c60` (worked on a throwaway
git worktree `/tmp/ngv2_sinkloc_wt`, now removed; live tree restored pristine).

## Problem (recap)
The empty-hunt fallback converts `pattern_scanner` regex hits into agy-shaped
candidates. For a dangerous call inside a function it attached the *enclosing
def* as the entrypoint regardless of whether that function forwards its
parameters into the sink. triton's `create_dockerfile_linux` builds a Dockerfile
*string* from literals and runs a fixed `docker build` argv — its params never
reach the subprocess argv — yet it was emitted as a CWE-78 entrypoint, the PoC
did `from build import create_dockerfile_linux; create_dockerfile_linux(payload)`,
and `poc_authenticity` (correctly) rejected it. 3/6 campaign targets died this
way (triton, keras, smolagents).

## Where the PoC's `sym` ORIGINATES (traced)
`poc_writer.default_resolver` (ngv2/poc_writer.py:135) parses the cited file and
ranks its TOP-LEVEL functions by how many CWE sink keywords appear in each
function body (`_collect_tokens`), plus a +10 boost if `finding.sink_name`
matches. It sets `entrypoint = functions_ranked[0]` and `symbols[0]` = same.
The per-CWE renderers (`_py_command_injection` etc.) call `_func_symbol(g)` =
`g.functions[0]`, producing `from <module> import <sym>; <sym>(payload)`.

For the triton file, `create_dockerfile_linux`'s body mentions `subprocess`, so
it scored highest and became `sym` — even though it does not forward taint.
The candidate's `sink_name`/`call_sites` (carried from the scanner hit) feed
`sink_hint`/`call_hint_tokens` in the resolver but were not enough to override
the enclosing-def's keyword score.

## Fix — two levers, both deterministic & fail-soft, stdlib-only

### 1. NEW module `ngv2/sink_localize.py` (taint-forwarding analyzer)
`localize_sink(file_path, line, sink_token) -> {symbol, forwarding, confidence, rank}`
(and `analyze_source(source, line, sink_token)` for already-read text).

Algorithm (intra-procedural taint forwarding over the containing FILE):
1. `ast.parse` the file (fail-soft: any SyntaxError/IO error → neutral
   `{'symbol':'','forwarding':False,'confidence':'unknown','rank':1}`, never raises).
2. Build an `enclosing[id(node)] -> FunctionDef` map via a single recursive walk
   (`_attach`): every node's enclosing function is the current function; a nested
   def becomes the enclosing function for its own children.
3. Collect all `ast.Call` nodes whose dotted func name (`_dotted_name`) matches a
   known dangerous sink token (`_SINK_TOKENS`, kept in sync by tail with
   `sink_extract._SINK_RULES`), optionally filtered by the passed `sink_token`.
   Pick the call closest to the hit `line` (ties → earliest by lineno,col) →
   deterministic.
4. Find the enclosing `FunctionDef`/`AsyncFunctionDef`. If none (module/class
   body) → `confidence='unknown'`, `symbol=''` (not a callable import-and-call
   entrypoint).
5. Compute taint set = function PARAMETERS (excluding `self`/`cls`; incl.
   posonly/kwonly/vararg/kwarg) grown to a fixpoint over local assignments
   (`Assign`/`AnnAssign`/`AugAssign`/walrus): a target becomes tainted if its
   value expression references any already-tainted name. `_names_in_expr` walks
   the whole value via `ast.walk`, so f-strings (`JoinedStr`), `BinOp`
   concatenation, `.format`/`.join`, and attribute/subscript chains
   (`request.args['x']` → root name `request`) all propagate.
6. FORWARDING := any positional/keyword arg of the dangerous call references a
   tainted name. YES → `confidence='high'`, `symbol=<func>`; NO → `'low'`.

Ranks: high=0, unknown=1, low=2 (lower sorts first; unknown kept ahead of
proven-non-forwarding so un-analyzable hits are never lost).

### 2. `ngv2/hunt_lead_client.py` — wire taint forwarding into the fallback
Old → new blocks:

(a) Import + config, after the existing `from ngv2 import sink_extract`:
```
+try:
+    from ngv2 import sink_localize as _sink_localize
+except Exception:  # pragma: no cover - fail-soft import
+    _sink_localize = None
 ...
+_FALLBACK_DROP_NONFORWARDING = True
+_CONFIDENCE_RANK = {'high': 0, 'unknown': 1, 'low': 2}
```

(b) `_candidate_from_hit(hit, target)` → `_candidate_from_hit(hit, target, repo=None)`:
it now (when `repo` is a str and a path is present) calls
`_sink_localize.localize_sink(abs_path, line, sink_name or None)`, and:
- if `confidence=='high'` and a symbol was found → sets `cand['sink_symbol']`
  and `cand['entrypoint']` to that forwarding function (the pin),
- attaches a transient `cand['_sink_confidence']` (high/low/unknown).
All wrapped in try/except → `unknown` on any error (current behavior preserved).

(c) `_fallback_candidates` now:
- passes `repo` to `_candidate_from_hit`,
- pops `_sink_confidence`; DROPS hits with `'low'` (proven non-forwarding) when
  `_FALLBACK_DROP_NONFORWARDING` (counts them; logged),
- stamps `_conf_rank` and sorts by **(conf_rank, CWE-priority, scanner order)**
  so forwarding entrypoints surface first; `unknown` hits stay (ranked 1),
- pops both transient keys before normalization; logs dropped + truncated counts.

`pattern_scanner.scan_directory`'s public contract is UNCHANGED (not touched).

### 3. `ngv2/poc_writer.py` — honor the pinned forwarding symbol
So the candidate-level pin actually changes `sym`:
- `_coerce_finding` now also copies `sink_symbol` (falling back to `entrypoint`)
  onto the coerced Finding:
```
+            setattr(coerced, 'sink_symbol', str(finding.get('sink_symbol', '') or finding.get('entrypoint', '') or ''))
```
- `default_resolver` reads `sink_symbol = getattr(finding,'sink_symbol','')` and
  adds **+100** to the function whose name matches it (vs +10 for sink_name, +5
  for call-site tokens), so a proven forwarding entrypoint outranks the noisy
  regex-enclosing def:
```
+        if sink_symbol and sink_symbol == name.lower():
+            score += 100
```

## Decision: DROP vs deprioritize
Chose **DROP** for proven `'low'` (non-forwarding) hits in the fallback
(`_FALLBACK_DROP_NONFORWARDING=True`) — these are exactly the wasted hunts. Hits
that cannot be analyzed (`'unknown'`: parse error, module-level, file unreadable)
are KEPT and ranked just below `'high'`, so the fix never silently loses a real
lead it merely couldn't prove. The flag makes reverting to deprioritize-only a
one-line change. The existing `test_hunt_fallback.py` fixture is all-forwarding
(`run(user)`→Popen, `danger(user)`→eval, `read(...,request)`→open(...request...)),
so DROP causes ZERO change to that oracle — verified.

## RED → GREEN evidence
Oracle `test_sink_localization.py` (12 tests). On pristine `ef15c60`:
`11 failed, 1 passed` — incl. the load-bearing
`assert 'create_dockerfile_linux' == 'run_real'` reproducing the exact bug.
After edits (worktree): `12 passed`.

## Regression
`python -m pytest -q -k "hunt or lead or pattern or sink or triage or poc_writer"`
→ **371 passed, 1599 deselected** (incl. the three named oracles:
`test_hunt_fallback.py`, `test_hunt_lead_client.py`, `test_triage_sink_accuracy.py`
= 23 passed, NO oracle adaptation needed).
Full suite: `1936 passed, 34 failed` — the 34 are ALL pre-existing
`tests/ngv2/test_z3_solver_adapter_wired.py` failures (documented OPEN owner item;
confirmed failing identically on pristine HEAD: `25 failed, 3 passed` for that
file alone). My change adds **zero** new failures and touches none of those files.

## files_touched
- `ngv2/sink_localize.py` — NEW (taint-forwarding analyzer; whole file).
- `ngv2/hunt_lead_client.py` — fallback wiring (whole file delivered).
- `ngv2/poc_writer.py` — sink_symbol pin honored in `_coerce_finding` +
  `default_resolver` (whole file delivered).
- `tests/test_sink_localization.py` — NEW hermetic oracle (whole file delivered).

## Not hermetically verifiable here
- End-to-end against the REAL triton/keras/smolagents repos behind
  `poc_authenticity` in a bwrap jail (needs the live campaign substrate + agy).
  The unit oracle reproduces the precise grounding bug
  (`create_dockerfile_linux` vs `run_real`) and proves the fix flips it; the live
  authenticity pass-rate uplift should be confirmed in a campaign run.
- The `_SINK_TOKENS` set is a curated mirror of `sink_extract._SINK_RULES`; if
  that catalog grows, add the new tail tokens here too (both are tail-matched,
  so a missing dotted prefix still matches by tail).
```
