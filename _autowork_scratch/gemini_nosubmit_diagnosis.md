# gemini (agy) dies-without-submitting — proven diagnosis (2026-06-20)

> Reconstructed (the original sub-agent's write did not persist to disk). Causal chain
> independently re-verified against live FS + source by the operator before fix dispatch.

## Verdict
Root cause = an `agy_pool` × `agent_jail` filesystem-shape collision over the unseeded
`.gemini/config` DIRECTORY. **NOT** a prompt / output-format / write-tool / auth-quota /
missing-context problem. agy receives the full prompt (promptLength=4469) and OAuths fine; it
never boots a conversation, so the prompt is silently dropped and it exits rc=0 with empty stdout.

## Located evidence
agy's stdout is in-memory (unpersisted), but its CLI logs land under the worker `$HOME` — with the
pool enabled that HOME is `<repo>/.agents/agy-pool/w{slot}`, so transcripts are at
`.agents/agy-pool/w{0,1}/.gemini/antigravity-cli/log/cli-*.log`. For the reconciler run
(`cli-20260620_192813.log`):
```
Print mode: starting (promptLength=4469, ...)            <- prompt received
OAuth: authenticated successfully as kevin...            <- auth fine
mkdir .../w0/.gemini/config: not a directory             <- ROOT
Ignoring user message, no active conversation
Print mode: SendUserMessage failed: no active conversation  <- prompt never hits the model
```
**42/42** recent pool agy runs contain `SendUserMessage failed: no active conversation`. The failed
tasks' outboxes (`.../gemini-r1-*/outbox/`) are empty — no `submission.py`. Claude succeeds because
its HOME is not the pool home and it never touches `.gemini/config`.

## Mechanism (5 links, all verified)
1. `agy_pool.enabled` flipped true (config.yaml:181, commit `179afa9`). Pool homes w0/w1 first
   materialized 2026-06-20 18:30/18:34 — the exact regression boundary (last gemini SUCCESS,
   claudecap-config-key, was 17:01, before pool materialization, when agy fell back to shared
   `~/.gemini`).
2. The pool seed list (`harness/agy_pool.py:19 _SEED_RELS`) seeds individual `.gemini/*.json`
   files but NOT the `.gemini/config` directory, so it is absent in a fresh pool home.
   `ensure_seeded` (`agy_pool.py:38-54`, live caller `orchestrator.py:248`) only copies those pairs.
3. `build_jail_argv(..., home=<pool_home>)` (orchestrator.py:429): with `<pool_home>/.gemini/config`
   absent, `agent_jail.py:266-277` mounts `--ro-bind /dev/null` over it → bwrap materializes a
   0-byte read-only FILE (verified: `.agents/agy-pool/w{0,1}/.gemini/config` = `-r--r--r--`, size 0,
   mtime = seed time).
4. The `config/projects` RW re-carve (`agent_jail.py:287-289`, the prior "gemini-jail-fix REV25") is
   gated on `os.path.isdir(config/projects)` → False → skipped.
5. agy 1.0.4 does `mkdir .gemini/config/projects` on startup → "not a directory" → no conversation
   → rc=0, empty output → `_extract_python_block("")` → `""` → no submission → "died without
   submitting (code 0)".

## Recommendation (goes through the pipeline — see brief_hooks_agy_pool_config_dir_seed.md)
Preferred: in `harness/agy_pool.py`, make `ensure_seeded` create `<pool_home>/.gemini/config/`
(and `config/projects/`) as real directories and idempotently repair a `config` that exists as a
non-directory, so the jail takes the `--ro-bind <config>` + projects-re-carve branch like the
shared home. New FS-effect deps as DEFAULTED kw-only params (`isdir`/`remove`) so the irreducible
`orchestrator.py:248` caller stays unchanged.
Alternative/belt-and-suspenders (NOT taken — irreducible): in `agent_jail.py:272-277`, stop
`/dev/null`-binding the dir-shaped `config` target.
Awareness only (NOT the fix, owner-gated): `workers.agy_pool.enabled:false` reverts agy to the
shared `~/.gemini` and immediately restores submissions, at the cost of per-worker HOME isolation.
