# CWE-22 (Path Traversal) detector research — NGv2 ML/AI-infra corpus

Scope: the Python sink/source patterns that matter for Path Traversal /
Arbitrary File Read-Write in the eligible corpus (sagemaker, triton, autogluon,
litellm, gptcache, text-generation-inference, modeldb). Grounded where possible
in the one real clone present under NGv2: `tmp/recon_clones/zilliztech-gptcache`.

## Why path traversal is the highest-value of the three in ML infra

The signature ML bug is **Zip/Tar Slip**: model artifacts ship as `.tar`/`.zip`
archives, and the loader calls `tarfile.extractall()` / `ZipFile.extractall()`
on the archive WITHOUT validating member names — a member named
`../../etc/cron.d/x` (or an absolute path) is written outside the intended
directory → RCE-grade arbitrary file write. This is endemic to model-loading
code (HuggingFace-style caches, SageMaker/Triton model unpacking, autogluon
artifact loaders). The second class is request-named file access: a download /
artifact / image endpoint that does `open(os.path.join(base, request_name))`
with `request_name = "../../secret"`.

## Sinks that matter — two tiers (the `taint` flag)

### INTRINSIC sinks (`taint: False`) — flagged on sight

| id                  | sink regex                                       | severity | rationale |
|---------------------|--------------------------------------------------|----------|-----------|
| pathtrav_extractall | `\.extractall\s*\(`                              | critical | Zip/Tar Slip — the canonical ML CWE-22 |
| pathtrav_tarfile    | `\btarfile\.open\s*\(`                           | high     | feeds extraction; archive source |
| pathtrav_zipfile    | `\bzipfile\.ZipFile\s*\(`                        | high     | feeds extraction; archive source |
| pathtrav_send_file  | `\b(send_file\|send_from_directory)\s*\(`        | high     | Flask download endpoint leaks files |

These are flagged whenever present: an extracted archive member or a served
path is attacker-controlled by definition; requiring an inline taint marker
would miss the most important class.

### TAINTED sinks (`taint: True`) — require a user-input marker

| id             | sink regex              | fires only when the ARGUMENTS look user-influenced |
|----------------|-------------------------|----------------------------------------------------|
| pathtrav_open  | `\bopen\s*\(`           | f-string / `..`/`+`/`%`/`.format` / id-substring (`filename`,`path`,`request`,`upload`,…) |
| pathtrav_join  | `\bos\.path\.join\s*\(` | same |

`open()` and `os.path.join()` are far too common to flag unconditionally — they
need positive evidence of attacker influence.

## Source / reachability proxy (the FP-killer)

Mirrors `_e2e_run/sink_quality.py`'s CWE-78 triage. For tainted sinks,
`_arg_is_tainted(line, match_end)` evaluates ONLY the call arguments (text after
the sink name) and:

1. Blanks string-literal bodies first (`_blank_literals`) so a marker inside a
   hardcoded path never counts. **This is the load-bearing fix:**
   `open("/path/to/audio.mp3")` contains the word `path` inside the literal; an
   early version flagged it. After blanking, the literal is empty → correctly
   dropped. Without this, every literal path containing `path`/`file`/`name` is
   a false positive.
2. Restricting the marker scan to the ARGUMENTS (not the whole line) is the
   second half of the fix: otherwise `os.path.join`'s own `path` token would
   make every `os.path.join` line self-trip the taint gate.
3. Treats an f-string prefix, a structural marker (`..`, `+`, `%`, `.format`),
   or a user-input identifier substring (`\w*(user|request|filename|path|
   upload|param|input|member|arcname|...)\w*` — substring so `request_filename`
   / `user_path` match while `base_dir` / `data_dir` do not) as taint.

## False-positive classes explicitly excluded

- **Hardcoded-literal paths**: `open("README.md")`, `open("/path/to/x.png")`
  (the blanking step). A literal path is not attacker-controllable.
- **`secure_filename(...)` sanitized lines** (`_SANITIZED`): werkzeug's
  `secure_filename` strips `..` and separators, neutralizing the traversal.
- **Vendored / test / docs / examples / tooling** files (`is_excluded_path`):
  drops gptcache `setup.py`, `docs/_exts/*`, `docs/bootcamp/*`.
- **Generic config-dir joins**: `os.path.join(data_dir, "data_map.txt")` — no
  user marker → not flagged (the substring word-list deliberately omits generic
  `dir`/`data`/`name`).
- **Comment lines**, **pruned dirs** (`SKIP_DIRS`).
- Out of band: traversal where the tainted component arrives across functions
  (inter-procedural), and archive members validated by a later `..`-check that
  the line scan cannot see — recall/precision trade-offs left to the taint engine.

## Real examples grepped from the corpus (zilliztech-gptcache)

TRUE POSITIVES (detector fires — confirmed by running the reference module):

1. `gptcache/utils/response.py:30`   `with open(img_path, "rb") as f:` → `pathtrav_open`.
2. `gptcache/manager/object_data/local_storage.py:19` `with open(f_path, "wb") as f:` → `pathtrav_open` (write).
3. `gptcache/embedding/timm.py:89`   `image = Image.open(image_path).convert("RGB")` → `pathtrav_open`.
4. `gptcache/manager/data_manager.py:117,174` `with open(self.data_path, ...)` → `pathtrav_open`.
5. `gptcache_server/server.py:78` `with zipfile.ZipFile(zip_filename, "w", ...)` → `pathtrav_zipfile`.

EXCLUDED (correctly NOT flagged):

6. `gptcache/adapter/replicate.py:40` `open("/path/to/merlion.png", "rb")` — literal path → dropped despite containing `path`.
7. `gptcache/adapter/openai.py:255` `open("/path/to/audio.mp3", "rb")` — literal path → dropped.
8. `setup.py` / `docs/_exts/docgen2.py` `open(os.path.join(...))` — path-excluded.

NOTE: gptcache has no `extractall`/`tarfile` site, but those are THE canonical
CWE-22 vector for the model-loading repos in the corpus (triton/sagemaker/
autogluon) and are the highest-severity rule. Measured on the full clone:
**9 findings (all genuine dynamic-path sinks), 0 literal-path FPs, risk=high**.

## Detector contract summary (see brief_hooks_ngv2_pathtrav_detect.md)

`ngv2/pathtrav_detect.py`, stdlib-only, pure/deterministic. Public surface:
`detect_path_traversal(repo_path)->dict`, `PATHTRAV_RULES` (rules-as-data, 6
rules, all CWE-22, intrinsic+tainted tiers), `SKIP_DIRS`, `is_excluded_path`.
Findings carry the `pattern_scanner` finding keys (`id/file/line/code/severity/
cwe/owasp/description`) so they flow through `ngv2/confidence_signals.py` unchanged.
