# Gap D — exact edits (apply to HEAD)

Two parts: (1) NEW module `ngv2/sink_extract.py` (already drafted at
`_autowork_scratch/gapfix/D_hunt_triage/sink_extract.py` — copy verbatim), and
(2) wire it into `ngv2/workers/triage.py` so triage deterministically
guarantees accurate `sink_name`/`call_sites` and reconciles `category`.

## Edit D.1 — new file `ngv2/sink_extract.py`
Copy `_autowork_scratch/gapfix/D_hunt_triage/sink_extract.py` verbatim to
`ngv2/sink_extract.py` (self-contained, stdlib-only).

## Edit D.2 — `ngv2/workers/triage.py` `_build_artifact` (~lines 233-236)

OLD:
```python
    body: Dict[str, Any] = {}
    body.update(record)
    body.setdefault('id', ident)
    body.setdefault('target', target)
```
NEW:
```python
    body: Dict[str, Any] = {}
    body.update(record)
    body = _enrich_sink(body)
    body.setdefault('id', ident)
    body.setdefault('target', target)
```

## Edit D.3 — add the fail-soft helper to `ngv2/workers/triage.py`
Add (e.g. just above `_build_artifact`):
```python
def _enrich_sink(body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from ngv2 import sink_extract
    except Exception:
        return body
    try:
        return sink_extract.enrich_finding(body)
    except Exception:
        return body
```

NOTE: verify the exact `_build_artifact` body lines + that `Dict`/`Any` are imported
in HEAD triage.py before applying; adapt anchors if HEAD drifted. The edit is purely
additive (existing assertions hold).

Oracle (already in scratch): `test_triage_sink_accuracy.py`. Verified by agent D:
RED on HEAD (ModuleNotFoundError sink_extract; triage yields sink_name=None/CWE-22),
GREEN after (subprocess→CWE-78, eval→CWE-95, open→CWE-22, requests→CWE-918, unknown
keeps original; reproducibility checks pass).

## Scoped follow-on (NOT in this drive): wire pattern_scanner as a deterministic
## fallback lead source in hunt_lead_client when agy returns [] (fixes mlflow-0).
