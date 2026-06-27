"""Deterministic model-file-format (MFF) vulnerability root-cause analyzer.

This module is *pure* and stdlib-only.  It NEVER loads, deserializes, imports,
or otherwise executes a model-file payload.  It works exclusively by:

  * consuming already-collected fuzz "score entries" (each describing whether a
    parser accepted or crashed on a malicious model file), and
  * inspecting raw header bytes / container metadata as opaque byte strings.

Public surface frozen by the committed oracle ``tests/test_mff_root_cause.py``:

  * ``FORMAT_SECURITY_MODELS`` / ``ATTACK_ROOT_CAUSES`` / ``ATTACK_CWES``
  * ``analyze_acceptance(entry, fmt)`` / ``analyze_crash(entry, fmt)``
  * ``_classify_crash(exit_code, stderr) -> (crash_type, severity, exploitable)``
  * ``generate_detection_rules(analyses, output_dir) -> list[str]``
  * ``analyze_score_file(score_path, output_path) -> dict``

All logic is deterministic: it relies on no wall clock, process environment,
randomness, or network connectivity.  Any timestamp / seed an analysis might
need would be accepted as an explicit parameter (none is currently required).
"""
from __future__ import annotations
import json
import os
from typing import Any, Dict, List, Tuple
FORMAT_SECURITY_MODELS: Dict[str, Dict[str, Any]] = {'joblib': {'deserialization': True, 'underlying_mechanism': 'python_pickle', 'risk_class': 'arbitrary_code_execution', 'parser_entry': 'joblib.load()', 'safe_alternative': 'skops.io.load (restricted)', 'known_defenses': ['restricted_unpickler', 'static_pickle_scanning', 'process_sandboxing']}, 'keras': {'deserialization': True, 'underlying_mechanism': 'lambda_layer_eval', 'risk_class': 'arbitrary_code_execution', 'parser_entry': 'keras.models.load_model()', 'safe_alternative': 'keras_v3_safe_mode_load', 'known_defenses': ['safe_mode', 'custom_object_allowlist', 'config_schema_validation']}, 'gguf': {'deserialization': False, 'underlying_mechanism': 'binary_header_parsing', 'risk_class': 'memory_corruption', 'parser_entry': 'gguf.GGUFReader()', 'safe_alternative': 'bounds_checked_gguf_reader', 'known_defenses': ['header_field_validation', 'tensor_bounds_checking']}, 'safetensors': {'deserialization': False, 'underlying_mechanism': 'json_header_offsets', 'risk_class': 'memory_corruption', 'parser_entry': 'safetensors.torch.load_file()', 'safe_alternative': 'safetensors.safe_open (lazy, validated)', 'known_defenses': ['header_length_validation', 'offset_range_validation', 'json_schema_validation']}, 'onnx': {'deserialization': True, 'underlying_mechanism': 'protobuf_custom_operators', 'risk_class': 'arbitrary_code_execution', 'parser_entry': 'onnx.load()', 'safe_alternative': 'onnx.checker + operator_allowlist', 'known_defenses': ['operator_allowlist', 'external_data_path_validation']}, 'tf_savedmodel': {'deserialization': True, 'underlying_mechanism': 'graphdef_custom_ops', 'risk_class': 'arbitrary_code_execution', 'parser_entry': 'tf.saved_model.load()', 'safe_alternative': 'restricted_op_savedmodel_loader', 'known_defenses': ['op_allowlist', 'disable_py_func_ops']}, 'tensorrt': {'deserialization': True, 'underlying_mechanism': 'serialized_engine_plan', 'risk_class': 'memory_corruption', 'parser_entry': 'tensorrt.Runtime.deserialize_cuda_engine()', 'safe_alternative': 'signed_engine_loader', 'known_defenses': ['engine_signature_verification', 'version_pinning']}}
ATTACK_ROOT_CAUSES: Dict[str, Dict[str, str]] = {'pickle_exec': {'root_cause': 'unsafe_pickle_deserialization', 'detail_template': '{parser} deserializes attacker-controlled pickle opcodes from the {format} payload, enabling arbitrary code execution via __reduce__.', 'defense_gap': 'missing_pickle_opcode_allowlist', 'detection_type': 'semgrep', 'detection_pattern_template': '$OBJ = {parser}', 'detection_message': 'Loading {format} model via {parser} deserializes untrusted pickle data and can execute arbitrary code (CWE-502).', 'validation_type': 'deserialization_allowlist', 'validation_check': 'enforce_restricted_unpickler', 'validation_reference': 'https://docs.python.org/3/library/pickle.html#restricting-globals'}, 'integer_overflow': {'root_cause': 'unchecked_integer_arithmetic', 'detail_template': '{parser} computes a buffer size from unchecked {format} header fields, overflowing and under-allocating before a copy.', 'defense_gap': 'missing_size_bounds_check', 'detection_type': 'semgrep', 'detection_pattern_template': '$N = $A * $B  # {format} header in {parser}', 'detection_message': 'Unvalidated size arithmetic in {parser} while parsing {format} headers can integer-overflow (CWE-190).', 'validation_type': 'bounds_check', 'validation_check': 'validate_header_dimensions', 'validation_reference': 'https://cwe.mitre.org/data/definitions/190.html'}, 'lambda_injection': {'root_cause': 'deserialized_lambda_layer_execution', 'detail_template': '{parser} reconstructs a Lambda layer from the {format} config and evaluates attacker-supplied Python at load time.', 'defense_gap': 'safe_mode_not_enforced', 'detection_type': 'semgrep', 'detection_pattern_template': 'Lambda(function=$F)  # {format} via {parser}', 'detection_message': 'Custom Lambda layer in {format} model executes arbitrary code through {parser} (CWE-94).', 'validation_type': 'config_allowlist', 'validation_check': 'enforce_keras_safe_mode', 'validation_reference': 'https://cwe.mitre.org/data/definitions/94.html'}, 'memmap_oob': {'root_cause': 'out_of_bounds_tensor_offset', 'detail_template': '{parser} maps tensor data using {format} offset/length fields without verifying they fall inside the file, enabling OOB reads.', 'defense_gap': 'missing_offset_range_validation', 'detection_type': 'semgrep', 'detection_pattern_template': 'memmap($BUF, offset=$O)  # {format} via {parser}', 'detection_message': 'Unvalidated tensor offsets in {format} headers allow out-of-bounds memory access in {parser} (CWE-125).', 'validation_type': 'bounds_check', 'validation_check': 'validate_tensor_offsets_within_file', 'validation_reference': 'https://cwe.mitre.org/data/definitions/125.html'}, 'header_overflow': {'root_cause': 'unbounded_header_length', 'detail_template': '{parser} trusts a {format} declared header length and reads/allocates it without an upper bound, enabling overflow.', 'defense_gap': 'missing_header_length_cap', 'detection_type': 'semgrep', 'detection_pattern_template': 'read($HEADER_LEN)  # {format} via {parser}', 'detection_message': 'Unbounded header length from {format} drives an unchecked read or allocation in {parser} (CWE-787).', 'validation_type': 'bounds_check', 'validation_check': 'cap_header_length', 'validation_reference': 'https://cwe.mitre.org/data/definitions/787.html'}, 'decompression_bomb': {'root_cause': 'unbounded_decompression_ratio', 'detail_template': '{parser} inflates compressed {format} streams without a ratio or size cap, enabling memory exhaustion.', 'defense_gap': 'missing_decompression_limit', 'detection_type': 'semgrep', 'detection_pattern_template': 'zlib.decompress($DATA)  # {format} via {parser}', 'detection_message': 'Unbounded decompression of {format} data in {parser} enables a decompression bomb / DoS (CWE-409).', 'validation_type': 'resource_limit', 'validation_check': 'enforce_max_decompressed_size', 'validation_reference': 'https://cwe.mitre.org/data/definitions/409.html'}}
ATTACK_CWES: Dict[str, str] = {'pickle_exec': 'CWE-502', 'integer_overflow': 'CWE-190', 'lambda_injection': 'CWE-94', 'memmap_oob': 'CWE-125', 'header_overflow': 'CWE-787', 'decompression_bomb': 'CWE-409', 'external_data_traversal': 'CWE-22', 'custom_operator': 'CWE-94'}
_MAGIC_SIGNATURES: List[Tuple[str, bytes]] = [('onnx', b'\x08'), ('gguf', b'GGUF'), ('zip_container', b'PK\x03\x04'), ('hdf5', b'\x89HDF\r\n\x1a\n'), ('pickle_proto2', b'\x80\x02'), ('pickle_proto3', b'\x80\x03'), ('pickle_proto4', b'\x80\x04'), ('pickle_proto5', b'\x80\x05')]
_DANGEROUS_PICKLE_OPCODES: List[Tuple[str, bytes]] = [('GLOBAL', b'c'), ('STACK_GLOBAL', b'\x93'), ('REDUCE', b'R'), ('BUILD', b'b'), ('INST', b'i'), ('OBJ', b'o'), ('NEWOBJ', b'\x81')]
_STDERR_SNIPPET_LEN: int = 500

def identify_format_from_bytes(data: bytes) -> str:
    """Best-effort format identification from leading magic bytes.

    Returns a coarse format label, or ``"unknown"`` when nothing matches.
    Operates only on the bytes object; it never parses or loads the payload.
    """
    if not data:
        return 'empty'
    for label, signature in _MAGIC_SIGNATURES:
        if data[:len(signature)] == signature:
            return label
    if len(data) >= 9 and data[8:9] == b'{':
        return 'safetensors'
    return 'unknown'

def scan_for_pickle_opcodes(data: bytes) -> List[str]:
    """Statically scan bytes for dangerous pickle opcodes.

    This inspects raw bytes only; it does NOT unpickle anything.  Returns the
    deduplicated, order-stable list of opcode names observed.
    """
    found: List[str] = []
    if not data:
        return found
    for label, opcode in _DANGEROUS_PICKLE_OPCODES:
        if opcode in data and label not in found:
            found.append(label)
    return found

def classify_cwe(attack_type: str, fallback: str='CWE-693') -> str:
    """Map an attack type to its CWE, deterministically.

    Falls back to a generic 'Protection Mechanism Failure' identifier when the
    attack type is not in the curated table.
    """
    return ATTACK_CWES.get(attack_type, fallback)

def _slug(value: str) -> str:
    """Lowercase, hyphenate an identifier for use in a rule id / filename."""
    return str(value).strip().lower().replace('_', '-').replace(' ', '-')

def _resolve_cwe(entry: Dict[str, Any], attack_type: str) -> str:
    """Prefer an explicit CWE on the entry, else derive from the table."""
    declared = entry.get('cwe')
    if isinstance(declared, str) and declared:
        return declared
    return ATTACK_CWES.get(attack_type, 'CWE-693')

def _parser_function(fmt: str) -> str:
    """Parser entry point for a format, or a neutral placeholder."""
    model = FORMAT_SECURITY_MODELS.get(fmt)
    if model and model.get('parser_entry'):
        return model['parser_entry']
    return '<unknown_parser>'

def _build_detection(template: Dict[str, str], fmt: str, parser: str) -> Dict[str, str]:
    """Render the semgrep detection shell for a known attack template."""
    pattern = template['detection_pattern_template'].format(format=fmt, parser=parser)
    message = template['detection_message'].format(format=fmt, parser=parser)
    return {'type': 'semgrep', 'pattern': pattern, 'message': message}

def _build_validation(template: Dict[str, str]) -> Dict[str, str]:
    """Render the validation shell for a known attack template."""
    return {'type': template['validation_type'], 'check': template['validation_check'], 'reference': template['validation_reference']}

def _manual_detection(attack_type: str, fmt: str) -> Dict[str, str]:
    return {'type': 'manual_review', 'pattern': '', 'message': "Unknown attack type '%s' observed on %s; manual security review required." % (attack_type, fmt)}

def _manual_validation() -> Dict[str, str]:
    return {'type': 'manual_review', 'check': 'manual_security_review', 'reference': ''}

def analyze_acceptance(entry: Dict[str, Any], fmt: str) -> Dict[str, Any]:
    """Classify an entry where a parser accepted a malicious model file.

    Returns a record carrying the root cause, CWE, parser entry point, defense
    gap, and recommended semgrep detection + validation shells.
    """
    attack_type = entry.get('attack_type', 'unknown')
    parser = _parser_function(fmt)
    cwe = _resolve_cwe(entry, attack_type)
    template = ATTACK_ROOT_CAUSES.get(attack_type)
    if template is None:
        return {'attack_type': attack_type, 'format': fmt, 'cwe': cwe, 'result': entry.get('result', 'accept'), 'root_cause': 'unknown_attack_type', 'detail': "Parser %s accepted a %s file exercising an unrecognized attack '%s'; manual triage required." % (parser, fmt, attack_type), 'parser_function': parser, 'defense_gap': 'unknown', 'recommended_detection': _manual_detection(attack_type, fmt), 'recommended_validation': _manual_validation()}
    return {'attack_type': attack_type, 'format': fmt, 'cwe': cwe, 'result': entry.get('result', 'accept'), 'root_cause': template['root_cause'], 'detail': template['detail_template'].format(format=fmt, parser=parser), 'parser_function': parser, 'defense_gap': template['defense_gap'], 'recommended_detection': _build_detection(template, fmt, parser), 'recommended_validation': _build_validation(template)}

def _classify_crash(exit_code: int, stderr: str) -> Tuple[str, str, bool]:
    """Classify a parser crash into ``(crash_type, severity, exploitable)``.

    Pure: derives everything from the exit code and stderr text.  ``stderr`` is
    matched case-insensitively.
    """
    text = (stderr or '').lower()
    if exit_code in (-11, 139) or 'segmentation fault' in text or 'sigsegv' in text:
        return ('segfault', 'critical', True)
    if exit_code in (-6, 134) or 'sigabrt' in text:
        if 'heap' in text or 'double free' in text or 'corruption' in text or ('free(): invalid' in text):
            return ('heap_corruption', 'critical', True)
        return ('abort', 'high', False)
    if 'heap buffer overflow' in text or 'heap-buffer-overflow' in text or 'double free' in text:
        return ('heap_corruption', 'critical', True)
    if exit_code == 124 or 'timed out' in text or 'timeout' in text:
        return ('timeout', 'medium', False)
    if 'memoryerror' in text or 'cannot allocate' in text or 'out of memory' in text or ('bad_alloc' in text):
        return ('oom', 'medium', False)
    for marker in ('safe_mode', 'safe mode', 'not allowed', 'is disabled', 'disabled for', 'is blocked', 'blocked', 'refused', 'not permitted', 'security check', 'security error'):
        if marker in text:
            return ('security_check', 'info', False)
    if 'assertionerror' in text or 'assertion failed' in text:
        return ('assertion', 'low', False)
    for marker in ('valueerror', 'keyerror', 'indexerror', 'struct.error', 'unpack', 'unicodedecodeerror', 'typeerror', 'eoferror', 'invalid', 'malformed', 'corrupt', 'decode', 'parse'):
        if marker in text:
            return ('parser_error', 'low', False)
    if 'error' in text or 'traceback' in text or 'exception' in text:
        return ('exception', 'low', False)
    return ('unknown', 'low', False)

def analyze_crash(entry: Dict[str, Any], fmt: str) -> Dict[str, Any]:
    """Classify an entry where a parser crashed on a malicious model file."""
    attack_type = entry.get('attack_type', 'unknown')
    parser = _parser_function(fmt)
    cwe = _resolve_cwe(entry, attack_type)
    exit_code = entry.get('exit_code', 0)
    stderr = entry.get('stderr', '') or ''
    snippet = stderr[:_STDERR_SNIPPET_LEN]
    crash_type, severity, exploitable = _classify_crash(exit_code, stderr)
    template = ATTACK_ROOT_CAUSES.get(attack_type)
    if template is None:
        detail = "Parser %s crashed (%s) on a %s file exercising an unrecognized attack '%s'." % (parser, crash_type, fmt, attack_type)
        defense_gap = 'unknown'
        detection = _manual_detection(attack_type, fmt)
        validation = _manual_validation()
    else:
        detail = template['detail_template'].format(format=fmt, parser=parser)
        defense_gap = template['defense_gap']
        detection = _build_detection(template, fmt, parser)
        validation = _build_validation(template)
    return {'attack_type': attack_type, 'format': fmt, 'cwe': cwe, 'result': entry.get('result', 'crash'), 'crash_type': crash_type, 'crash_severity': severity, 'exploitable': exploitable, 'exit_code': exit_code, 'stderr_snippet': snippet, 'detail': detail, 'parser_function': parser, 'defense_gap': defense_gap, 'recommended_detection': detection, 'recommended_validation': validation}

def _render_rule_yaml(rule_id: str, analysis: Dict[str, Any], detection: Dict[str, str]) -> str:
    """Render a single semgrep rule as a YAML document string.

    String values are JSON-encoded (valid YAML scalars) so arbitrary content
    cannot break the document.
    """
    lines = ['rules:', '  - id: ' + rule_id, '    message: ' + json.dumps(detection.get('message', '')), '    severity: WARNING', '    languages:', '      - python', '    metadata:', '      cwe: ' + json.dumps(analysis.get('cwe') or 'unknown'), '      format: ' + json.dumps(analysis.get('format', '')), '      attack_type: ' + json.dumps(analysis.get('attack_type', '')), '      root_cause: ' + json.dumps(analysis.get('root_cause', '')), '      defense_gap: ' + json.dumps(analysis.get('defense_gap', '')), '    patterns:', '      - pattern: ' + json.dumps(detection.get('pattern', ''))]
    return '\n'.join(lines) + '\n'

def generate_detection_rules(analyses: List[Dict[str, Any]], output_dir: str) -> List[str]:
    """Write a semgrep YAML rule per *unique* semgrep-eligible analysis.

    Manual-review entries are skipped; rule ids are derived deterministically
    from ``format`` + ``attack_type`` and used to dedupe.  Returns the list of
    file paths written.
    """
    os.makedirs(output_dir, exist_ok=True)
    written: List[str] = []
    seen: set = set()
    for analysis in analyses:
        detection = analysis.get('recommended_detection') or {}
        if detection.get('type') != 'semgrep':
            continue
        fmt = analysis.get('format', 'unknown')
        attack_type = analysis.get('attack_type', 'unknown')
        rule_id = 'mff-' + _slug(fmt) + '-' + _slug(attack_type)
        filename = rule_id + '.yaml'
        if filename in seen:
            continue
        seen.add(filename)
        path = os.path.join(output_dir, filename)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(_render_rule_yaml(rule_id, analysis, detection))
        written.append(path)
    return written

def _summarize(fmt: str, total: int, acceptances: int, crashes: int, rules_written: List[str]) -> str:
    """Build a short deterministic human-readable summary line."""
    return 'Format %s: analyzed %d result(s) -- %d acceptance(s), %d crash(es); %d detection rule(s) emitted.' % (fmt, total, acceptances, crashes, len(rules_written))

def analyze_score_file(score_path: str, output_path: str) -> Dict[str, Any]:
    """Analyze a collected fuzz score file and write a JSON summary report.

    The score file is JSON of shape ``{"format": str, "results": [entry, ...]}``.
    Each entry is dispatched by its ``result``: ``accept`` -> acceptance
    analysis, ``crash`` -> crash analysis, anything else (e.g. ``reject``) is
    skipped.  This function never loads any model payload -- it only reads JSON.
    """
    with open(score_path, 'r', encoding='utf-8') as handle:
        score = json.load(handle)
    fmt = score.get('format', 'unknown')
    results = score.get('results') or []
    analyses: List[Dict[str, Any]] = []
    acceptances = 0
    crashes = 0
    for entry in results:
        outcome = entry.get('result')
        if outcome == 'accept':
            analyses.append(analyze_acceptance(entry, fmt))
            acceptances += 1
        elif outcome == 'crash':
            analyses.append(analyze_crash(entry, fmt))
            crashes += 1
    out_dir = os.path.dirname(os.path.abspath(output_path))
    rules_dir = os.path.join(out_dir, 'mff_detection_rules')
    rules_written = generate_detection_rules(analyses, rules_dir)
    report: Dict[str, Any] = {'format': fmt, 'total_analyzed': len(analyses), 'acceptances': acceptances, 'crashes': crashes, 'analyses': analyses, 'rules_written': rules_written, 'summary': _summarize(fmt, len(analyses), acceptances, crashes, rules_written)}
    with open(output_path, 'w', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    return report