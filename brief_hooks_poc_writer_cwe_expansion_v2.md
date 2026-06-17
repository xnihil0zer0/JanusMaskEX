---
title: poc_writer CWE-20 import-call template (ledger-proven gap) — atomic 2-leaf manifest
meta_task_type: implementation
working_dir: /home/xnihil0zer0/NobleGreedv2
required_task_ids:
  - oracle_poc_writer_cwe20
  - impl_poc_writer_cwe20
files_touched:
  - tests/test_poc_writer_cwe20_expansion.py
  - ngv2/poc_writer.py
verification_command: python -m pytest tests/test_poc_writer_cwe20_expansion.py tests/test_poc_writer_cwe94_cwe22.py tests/test_poc_writer_wired.py -q
---

# Title

poc_writer CWE-20 import-call template expansion — add ONE detonatable,
source-authentic PoC template for CWE-20 (Improper Input Validation), the ONLY
ledger-proven un-templatable CWE class that fail-closes the live hunt at the
`poc_authenticity` gate (LEDGER: `no_template_cwe20`).

# Why this re-issue exists (root cause of the prior exhaustion)

The prior held brief (`brief_hooks_poc_writer_cwe_expansion.md`, EXHAUSTED
2026-06-16) declared a 2-file manifest (impl `ngv2/poc_writer.py` + a NEW test
file) but the planner emitted a SINGLE `data_model` task with `files_touched`
containing ONLY `ngv2/poc_writer.py` — the test file NEVER landed → the
verification_command failed with `exit=4 "file or directory not found:
tests/test_poc_writer_cwe_expansion.py"`. It was NOT a template-logic failure.

The fix is purely structural: force a TWO-leaf decomposition so BOTH files land
atomically — a `test_authoring` leaf that creates the NEW test file, and an
`implementation`/partial-edit leaf that ADDITIVELY edits the existing module.
This is an EXTERNAL working_dir edit (working_dir is in `external_roots.allow`,
so the acceptance gate's `worktree_root` resolves to the NGv2 root). The oracle
test imports `get_template('CWE-20')`, which does NOT resolve until the impl
lands, so the oracle is RED standalone and is a legitimate **fix-forward
red-pair**: it is accepted RED through the acceptance gate via
`is_fix_forward_redpair` (mutation_target `ngv2.poc_writer` EXISTS under the NGv2
worktree_root; the paired impl runs the oracle's OWN test file), and the impl
turns it GREEN. The two leaves are NOT independent — the oracle MUST be RED until
the impl lands.

# Scope

The prior brief speculatively added FIVE CWE classes (CWE-20/79/117/732/312).
ONLY CWE-20 is ledger-proven (`no_template_cwe20`). CWE-79/117/732/312 have NO
in-tree artifact proving their finding counts, so they are explicitly DEFERRED
to a documented follow-up (see Non-goals). This brief ships ONLY the CWE-20
import-call reach-then-mark template.

# Goal

The new template makes `get_template('CWE-20')` (and its aliases) resolve, and
`_resolve_template(finding)` resolve a finding carrying `cwe='CWE-20'`. The
rendered PoC imports the REAL target symbol (so `poc_authenticity` classifies it
`real_target` / `may_confirm=True`) and writes a per-CWE filesystem signature
once the sink is reached (so the FS-snapshot detonation oracle confirms). This
was prototyped and PROVEN end-to-end — reproduce the append + test SOURCE
VERBATIM.

# Inputs

`ngv2/poc_writer.py` at HEAD. The append block relies ONLY on names already
defined in that module at import time (all confirmed present on HEAD):
- `_TEMPLATE_LIST` (line 377) — list of CWETemplate; `PER_CWE_TEMPLATES` (line
  378) is rebuilt from it by the loop at lines 379-382.
- `_SINK_CWE_RULES` (present in source) — additive tuple-concat extension only.
- `CWETemplate`, `_make_js`, `_func_symbol`, `_py_header`, `Grounding` — all
  present. Import NOTHING new.

# Required append (reproduce VERBATIM at end of ngv2/poc_writer.py)

NESTED-QUOTE HAZARD: the body is a Python f-string containing literal `\n`,
single quotes, and `!r` conversions. Emit it EXACTLY as written — do NOT
re-escape, collapse, or "fix" the backslashes; they are correct as-is (verified
by execution). Emit triple-DOUBLE-quote (`"""`) strings if any docstring is
needed, NEVER triple-single (`'''`).

```python


# === CWE-20 import-call template (appended; additive, end-of-module) ===
def _py_improper_input_validation(g, marker, fs):  # CWE-20
    sym = _func_symbol(g); sig = fs + '_inputval'
    body = (f"payloads = ['amazon.com.{marker}.attacker.example', '{marker}-amazon.com']\n_reached = False\nfor _p in payloads:\n    try:\n        {sym}(_p); _reached = True\n    except Exception as exc:\n        print('reached sink:', exc); _reached = True\nif _reached:\n    open({sig!r}, 'w').close()\nprint('{marker}')\n")
    return _py_header(g, sym) + body

_EXT_TEMPLATES = [
    ('CWE-20', ('improper_input_validation', 'incomplete_url_substring_sanitization', 'input_validation'), _py_improper_input_validation),
]
for _c, _al, _fn in _EXT_TEMPLATES:
    _t = CWETemplate(_c, tuple(_al), _fn, _make_js(_c, 'func'))
    _TEMPLATE_LIST.append(_t)
    PER_CWE_TEMPLATES[_c] = _t
    for _a in _al:
        PER_CWE_TEMPLATES.setdefault(_a, _t)
```

# Required test file (reproduce VERBATIM as tests/test_poc_writer_cwe20_expansion.py)

```python
import os
import subprocess
import sys
import tempfile

import pytest

from ngv2.poc_writer import Grounding, get_template, _resolve_template
from ngv2.poc_authenticity_gate import classify_poc_authenticity

NEW = [
    ('CWE-20', '_inputval'),
]


def _fake_target_dir():
    tmp = tempfile.mkdtemp()
    with open(os.path.join(tmp, 'fakevuln.py'), 'w') as fh:
        fh.write("def vuln_sink(x):\n    return '<r>' + str(x) + '</r>'\n")
    return tmp


@pytest.mark.parametrize('cwe,suffix', NEW)
def test_new_cwe_resolves_authentic_and_detonatable(cwe, suffix):
    template = get_template(cwe)
    assert template.cwe == cwe
    tmp = _fake_target_dir()
    g = Grounding(module='fakevuln', symbols=['vuln_sink'],
                  functions=['vuln_sink'], source_dir=tmp)
    src = template.render_py(g, 'VULNERABLE', 'pwned_marker')
    verdict = classify_poc_authenticity(src, ['fakevuln'])
    assert verdict['mode'] == 'real_target'
    assert verdict['may_confirm'] is True
    run = tempfile.mkdtemp()
    result = subprocess.run([sys.executable, '-c', src], cwd=run,
                            capture_output=True, text=True, timeout=30)
    assert os.path.exists(os.path.join(run, 'pwned_marker' + suffix))
    assert 'VULNERABLE' in result.stdout


def test_finding_cwe_field_resolves_template():
    class _Finding:
        cwe = 'CWE-20'
        sink_name = ''
        title = ''
        description = ''
        id = 'HUNT-1'

    assert _resolve_template(_Finding()).cwe == 'CWE-20'


def test_existing_templates_unbroken():
    for cwe in ('CWE-78', 'CWE-22', 'CWE-89', 'CWE-94', 'CWE-918', 'CWE-502'):
        assert get_template(cwe).cwe == cwe
```

# Implementation notes / scope

The impl is ADDITIVE: register ONE new CWETemplate into `_TEMPLATE_LIST` (and
into `PER_CWE_TEMPLATES` by canonical id + aliases via setdefault) plus the new
`_py_improper_input_validation` renderer. Do NOT reproduce `ngv2/poc_writer.py`
whole — use the R-ANCHOR additive insertion path (`__JANUSMASK_PATCHES__`),
inserting the new top-level symbols at end-of-module. No existing function,
`_TEMPLATE_LIST` entry, or `_SINK_CWE_RULES` row is modified.

NESTED-QUOTE HAZARD: the renderer body is an f-string with literal `\n`, single
quotes, and `!r`. Emit it EXACTLY as written; emit triple-DOUBLE-quote (`"""`)
strings, NEVER triple-single (`'''`).

# Deliverables

1. `tests/test_poc_writer_cwe20_expansion.py` = the test file above, VERBATIM.
2. `ngv2/poc_writer.py` = current HEAD + the additive append block, via the
   R-ANCHOR partial-edit path (NOT a whole-file rewrite).
3. `python -m pytest tests/test_poc_writer_cwe20_expansion.py tests/test_poc_writer_cwe94_cwe22.py tests/test_poc_writer_wired.py -q` passes — the new
   suite is green because both files ship in the SAME plan; the two existing
   suites prove no regression.

# Non-goals

- DEFERRED follow-up (NOT this brief): CWE-79/117/732/312 templates — no in-tree
  artifact proves those finding counts, so they are out of scope here.
- NO modification of any existing `_py_*` renderer, `_TEMPLATE_LIST` entry, or
  `_SINK_CWE_RULES` row — strictly additive.
- NO source-driving (HTTP-client) payloads and NO `payload_bank` change — the
  import-call reach-then-mark path is the deliverable.
- NO new module beyond the one authored test file; no refactor.
- This is unit-scoped; broad cross-module **integration** testing of the live
  hunt FSM is explicitly out of scope and excused.

# Required plan shape

Decompose into EXACTLY these TWO leaves, using these EXACT task_ids (declared in
frontmatter `required_task_ids`; validate_plan rejects the plan with
`missing_required_task` if any is absent). This forces BOTH files to land
atomically so the test file is never dropped. It IS a fix-forward red-pair: the
oracle leaf is RED-by-missing-symbol on the EXISTING external module
`ngv2.poc_writer` and is accepted RED via `is_fix_forward_redpair`; the impl leaf
(which runs the oracle's OWN test file as its vcmd) turns it GREEN. Do NOT make
the oracle standalone-green.

1. task_id: oracle_poc_writer_cwe20
   - meta_task_type: test_authoring
   - files_touched: [tests/test_poc_writer_cwe20_expansion.py]
   - mutation_target: ngv2.poc_writer   (bare dotted module-under-test; its file
     ngv2/poc_writer.py EXISTS — existing module, NOT a new module)
   - verification_command: python -m pytest tests/test_poc_writer_cwe20_expansion.py tests/test_poc_writer_cwe94_cwe22.py tests/test_poc_writer_wired.py -q
   - dependencies: []
   - Authors the test file of deliverable 1 VERBATIM. spec_author: null.
   - non_goals MUST contain the word "integration" (integration-excused scope).
   - test_spec.regression_tests MUST contain >= 2 entries.

2. task_id: impl_poc_writer_cwe20
   - meta_task_type: implementation
   - files_touched: [ngv2/poc_writer.py]
   - verification_command: python -m pytest tests/test_poc_writer_cwe20_expansion.py tests/test_poc_writer_cwe94_cwe22.py tests/test_poc_writer_wired.py -q
   - dependencies: [oracle_poc_writer_cwe20]
   - Implements the additive append (the new renderer + `_EXT_TEMPLATES`
     registration loop) via the R-ANCHOR/`__JANUSMASK_PATCHES__` partial-edit
     path; do NOT reproduce ngv2/poc_writer.py whole.
   - non_goals MUST contain the word "integration" (integration-excused scope).
   - test_spec.regression_tests MUST contain >= 2 entries.

# test_spec regression_tests (apply to BOTH leaves, >= 2 entries)

- tests/test_poc_writer_cwe94_cwe22.py (existing suite must stay green — no
  regression from the additive append).
- tests/test_poc_writer_wired.py (existing wiring suite must stay green).
- test_existing_templates_unbroken (CWE-78/22/89/94/918/502 still resolve to
  their own templates after the additive registration).
