"""ngv2/artifact_harvester.py -- deterministic stage-output parser.

A PURE core ``parse_stage_artifact(filename, content, phase) -> dict | None``
turns one pipeline-stage output file into a contract-shaped artifact dict
(a PoC artifact or a report artifact), classifying purely from the filename
suffix + content (no disk, no network, no clock, no randomness). A THIN I/O
wrapper ``harvest_stage_artifacts(phase, output_dir) -> list[dict]`` sweeps a
directory, reads each file, delegates to the pure core, and collects every
non-None result -- holding no classification logic of its own.
"""
import json
import os
from typing import Optional

def parse_stage_artifact(filename: str, content: str, phase: str) -> Optional[dict]:
    """Classify one stage-output file into a contract-shaped artifact dict.

    Pure and deterministic: depends only on ``filename`` and ``content``. The
    ``phase`` argument is accepted as context only and never alters the result.
    Returns None for anything that does not match a known rule (and, for JSON
    reports, fail-closed to None on invalid JSON).
    """
    if filename.endswith('_poc.py'):
        return {'kind': 'poc', 'language': 'python', 'source': content, 'filename': filename}
    if filename.endswith('_poc.js'):
        return {'kind': 'poc', 'language': 'javascript', 'source': content, 'filename': filename}
    if filename.endswith('_submission.md'):
        return {'kind': 'report', 'format': 'markdown', 'markdown': content, 'filename': filename}
    if filename.endswith('_report.json') or filename == 'detonation_report.json':
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        return {'kind': 'report', 'verdict': parsed.get('verdict'), 'data': parsed, 'filename': filename}
    # additive: raw per-phase JSON outputs the workers emit directly (the
    # _runner aggregate <phase>_report.json is already handled above). Fail-closed
    # on invalid JSON, mirroring the _report.json rule. Existing rules unchanged.
    _phase_json_kind = {
        'novelty.json': 'novelty',
        'report.json': 'report',
        'hunt.json': 'finding',
        'triage.json': 'triage',
        'verify.json': 'verify',
    }
    kind = _phase_json_kind.get(filename)
    if kind is None and filename.endswith('_finding.json'):
        kind = 'finding'
    if kind is not None:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        return {'kind': kind, 'data': parsed, 'filename': filename}
    return None

def harvest_stage_artifacts(phase: str, output_dir: str) -> list[dict]:
    """Sweep ``output_dir`` and collect contract-shaped artifacts.

    The ONLY filesystem-touching code: it lists files directly in
    ``output_dir``, reads each file's text, delegates classification to
    ``parse_stage_artifact``, and collects every non-None result. Contains no
    classification logic of its own.
    """
    artifacts: list[dict] = []
    for name in os.listdir(output_dir):
        path = os.path.join(output_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, 'r') as handle:
            content = handle.read()
        result = parse_stage_artifact(name, content, phase)
        if result is not None:
            artifacts.append(result)
    return artifacts