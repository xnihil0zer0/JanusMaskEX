# CWE-918 (SSRF) detector research — NGv2 ML/AI-infra corpus

Scope: the Python sink/source patterns that actually matter for Server-Side
Request Forgery in the eligible corpus (sagemaker, triton, autogluon, litellm,
gptcache, text-generation-inference, modeldb). Grounded where possible in the
one real clone present under NGv2:
`tmp/recon_clones/zilliztech-gptcache`.

## Why SSRF is in scope for this corpus

ML-serving / LLM-gateway code fetches remote resources constantly: pulling a
model/artifact by URL, proxying an upstream LLM/provider endpoint, downloading
an image/audio asset named in a request, resolving a webhook/callback. Whenever
the destination URL is influenced by request input, an attacker can pivot the
server into the internal network (cloud metadata `169.254.169.254`, internal
admin ports, `file://`). SSRF (CWE-918) + deser (CWE-502) + path-trav (CWE-22)
are 37.9% of paid huntr findings; the current scanner hunts none of SSRF.

## Sinks that matter (the detection surface)

The detector flags an HTTP-client call whose URL is NOT a constant literal:

| Family   | Sink regex (line-level)                                              | Notes |
|----------|---------------------------------------------------------------------|-------|
| requests | `\brequests\.(get\|post\|put\|patch\|delete\|head\|request)\s*\(`    | dominant in this corpus |
| urllib   | `\b(urllib\.request\.urlopen\|urlopen\|urllib\.request\.Request)\s*\(` | stdlib, also `Request(url)` |
| httpx    | `\bhttpx\.(get\|post\|put\|patch\|delete\|head\|request\|stream)\s*\(` | async LLM gateways (litellm/gptcache) |

These three families cover the corpus. `aiohttp` `session.get(url)` and a bare
`client.get(url)` were DELIBERATELY excluded: a generic `\w*(session|client)\.get\(`
rule collides with SQLAlchemy `session.get(Model, id)` and produces heavy FPs
for little extra recall. If a future repo needs aiohttp, add a dedicated
`aiohttp.ClientSession` rule rather than a generic session matcher.

## Source / reachability proxy (the FP-killer)

Line-level regex cannot prove taint, so — mirroring how `_e2e_run/sink_quality.py`
triages CWE-78 (drops `def eval`, `model.eval()`, pure-literal `os.system("ls")`)
— the SSRF detector keeps a finding ONLY when the URL argument is non-constant:

1. Drop the finding if the URL is a single hardcoded string literal with no
   dynamic marker: `requests.get("https://fixed.example.com/health")` → NOT SSRF.
2. Keep it if the argument is a name (`requests.get(url)`), an f-string
   (`requests.get(f"https://{host}/api")`), a concatenation
   (`requests.get("https://api/" + path)`), or a `.format`/`%` build.
3. **Critical subtlety:** dynamic markers are evaluated AFTER blanking
   string-literal bodies. Otherwise a hardcoded URL containing a marker word
   (e.g. `"https://user.example.com"` contains `user`) would be a false
   positive. `_blank_literals` replaces `"...."` with `""` before the marker
   scan; an f-string prefix is detected on the raw tail.

## False-positive classes explicitly excluded

- **Vendored / test / docs / examples / tooling** files (`is_excluded_path`,
  mirroring sink_quality `_EXCLUDE_PATH`): a sink in `tests/`, `docs/`,
  `examples/`, `vendor/`, `_vendor/`, `scripts/`, `.github/`, `setup.py` is not a
  shipped, externally-reachable library sink. In gptcache this drops
  `docs/bootcamp/streamlit/.../imagen.py:46  requests.get(image_url)`.
- **Hardcoded-literal URLs** (health checks, fixed provider base URLs).
- **Marker-inside-literal** (the blanking step above).
- **Comment / docstring lines** (`#`-prefixed lines skipped).
- **Pruned dirs** (`SKIP_DIRS`: `.git`, `node_modules`, `.venv`, `site-packages`, …).
- Out of band: SSRF where the URL is built across functions (inter-procedural)
  is NOT caught — that is the next-stage taint engine's job, not this recon pass.

## Real examples grepped from the corpus (zilliztech-gptcache)

TRUE POSITIVES (detector fires — confirmed by running the reference module):

1. `gptcache/manager/data_manager.py:295`
   `dep.dep_type.data = self.o.put(requests.get(dep.data).content)`
   — URL is `dep.data` (dependency-derived, non-constant) → `ssrf_requests`.
2. `gptcache/utils/response.py:23`
   `img_content = requests.get(url).content`
   — URL is the `url` parameter → `ssrf_requests`.
3. `gptcache/client.py:34,47` `async with httpx.AsyncClient() as client:`
   — the corpus uses httpx for outbound calls (the `.get(url)` request line is
   the sink the `ssrf_httpx` rule targets).

EXCLUDED (correctly NOT flagged):

4. `docs/bootcamp/streamlit/gptcache-streamlit-image/imagen.py:46`
   `response = requests.get(image_url)` — dynamic, but under `docs/` → path-excluded.

Measured on the full clone: **2 findings, 0 false positives, risk=medium**.

## Detector contract summary (see brief_hooks_ngv2_ssrf_detect.md)

`ngv2/ssrf_detect.py`, stdlib-only, pure/deterministic. Public surface:
`detect_ssrf(repo_path)->dict`, `SSRF_RULES` (rules-as-data, 3 rules, all
CWE-918), `SKIP_DIRS`, `is_excluded_path`. Findings carry the
`pattern_scanner` finding keys (`id/file/line/code/severity/cwe/owasp/
description`) so they flow through `ngv2/confidence_signals.py` unchanged.
