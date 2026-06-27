"""Deterministic MFF (malicious-model-file) parser-scoring shell.

The legacy scorer crafted malicious model files and ran each against a real
parser library in a timed subprocess, classifying the parser's response as
crash / reject / accept / error.  That capability is distilled here into a
PURE, INJECTED-SEAM contract: this module supplies deterministic constants
and a classification core, and takes the two external effects -- file
*crafting* and parser *execution* -- as injected callables.  Nothing here
crafts a real malicious file nor runs a real parser; callers drive the shell
with mock / scripted seams.

Seam shapes::

    crafter(file_path: str, spec: dict) -> None        # raise on craft failure
    runner(command: str, file_path: str) -> (exit_code, stdout, stderr, timed_out)

The module is stdlib-only and fully deterministic: every timestamp arrives as
an explicit ISO-string parameter, so identical inputs always produce identical
output.
"""
from __future__ import annotations
import json
import os
import tempfile
from typing import Callable, Dict, List, Optional, Tuple
PARSER_COMMANDS: Dict[str, str] = {'joblib': 'python -c "import joblib; joblib.load(\'{file}\')"', 'keras': 'python -c "import keras; keras.models.load_model(\'{file}\')"', 'onnx': 'python -c "import onnx; onnx.load(\'{file}\')"', 'safetensors': 'python -c "from safetensors.torch import load_file; load_file(\'{file}\')"', 'gguf': 'python -c "import gguf; gguf.GGUFReader(\'{file}\')"', 'tf_savedmodel': 'python -c "import tensorflow as tf; tf.saved_model.load(\'{file}\')"', 'tensorrt': 'python -c "import tensorrt as trt; trt.Runtime(trt.Logger()).deserialize_cuda_engine(open(\'{file}\',\'rb\').read())"'}
RESULT_KINDS: Tuple[str, ...] = ('crash', 'reject', 'accept', 'error')
BATTERY_FIELDS: Tuple[str, ...] = ('format', 'attack_type', 'file_path', 'cwe', 'description')
TEST_RESULT_FIELDS: Tuple[str, ...] = ('result', 'exit_code', 'stdout', 'stderr', 'exception_type', 'time_s')
SCORE_FIELDS: Tuple[str, ...] = ('format', 'cycle', 'round', 'timestamp', 'total_attacks', 'results', 'acceptance_rate', 'parser_version', 'attacks')
CRASH_SIGNALS = frozenset({-11, -6, -4, -8, -7})
PARSER_TIMEOUT_S: int = 10
REJECT_PATTERNS: List[str] = ['untrusted', 'unsafe', 'security', 'corrupt', 'malformed', 'invalid', 'bad magic', 'magic', 'cannot load', 'refus', 'forbidden', 'not allowed', 'unsupported', 'parse error', 'decode error', 'valueerror', 'oserror', 'keyerror']
CRASH_INDICATORS: List[str] = ['segmentation fault', 'core dumped', 'aborted', 'bus error', 'stack smashing', 'double free', 'buffer overflow', 'sigsegv', 'sigabrt', 'fatal error', 'terminate called']
FORMAT_ALIASES: Dict[str, str] = {'tf': 'tf_savedmodel', 'tensorflow': 'tf_savedmodel', 'saved_model': 'tf_savedmodel', 'savedmodel': 'tf_savedmodel', 'trt': 'tensorrt', 'h5': 'keras', 'sklearn': 'joblib', 'pickle': 'joblib', 'st': 'safetensors'}
ATTACK_SPECS: Dict[str, List[Dict[str, str]]] = {'joblib': [{'attack_type': 'reduce_os_system', 'ext': '.pkl', 'cwe': 'CWE-502', 'description': 'pickle __reduce__ invoking os.system'}, {'attack_type': 'reduce_subprocess', 'ext': '.pkl', 'cwe': 'CWE-502', 'description': 'pickle __reduce__ spawning a subprocess'}, {'attack_type': 'nested_object_bomb', 'ext': '.pkl', 'cwe': 'CWE-400', 'description': 'deeply nested object graph causing resource exhaustion'}], 'keras': [{'attack_type': 'lambda_layer_rce', 'ext': '.h5', 'cwe': 'CWE-502', 'description': 'Lambda layer carrying arbitrary marshalled code'}, {'attack_type': 'custom_object_payload', 'ext': '.keras', 'cwe': 'CWE-502', 'description': 'custom-object deserialization payload'}], 'onnx': [{'attack_type': 'oversized_dim', 'ext': '.onnx', 'cwe': 'CWE-190', 'description': 'integer overflow via an oversized tensor dimension'}, {'attack_type': 'malformed_graph', 'ext': '.onnx', 'cwe': 'CWE-20', 'description': 'malformed protobuf graph definition'}], 'safetensors': [{'attack_type': 'header_size_overflow', 'ext': '.safetensors', 'cwe': 'CWE-190', 'description': 'declared header length overflows the file'}, {'attack_type': 'out_of_bounds_offset', 'ext': '.safetensors', 'cwe': 'CWE-125', 'description': 'tensor offset points outside the buffer'}], 'gguf': [{'attack_type': 'metadata_count_overflow', 'ext': '.gguf', 'cwe': 'CWE-190', 'description': 'metadata key-value count overflow'}, {'attack_type': 'truncated_tensor', 'ext': '.gguf', 'cwe': 'CWE-125', 'description': 'tensor data truncated past its declared size'}], 'tf_savedmodel': [{'attack_type': 'op_attr_overflow', 'ext': '.pb', 'cwe': 'CWE-190', 'description': 'op attribute integer overflow in GraphDef'}, {'attack_type': 'malformed_graphdef', 'ext': '.pb', 'cwe': 'CWE-20', 'description': 'malformed GraphDef protobuf'}], 'tensorrt': [{'attack_type': 'engine_header_corruption', 'ext': '.engine', 'cwe': 'CWE-20', 'description': 'corrupted serialized-engine header'}]}

def _classify_result(exit_code: int, stdout: str, stderr: str, timed_out: bool=False) -> str:
    """Classify a parser invocation into one of ``RESULT_KINDS``.

    Precedence:
      * a timeout or a fatal-signal exit code is a *crash*;
      * a clean exit (0) means the parser swallowed the malicious file -> *accept*;
      * on a non-zero exit, a crash indicator in the output is a *crash*,
        otherwise any recognized output (or none) is treated as a *reject*.
    """
    if timed_out:
        return 'crash'
    if exit_code in CRASH_SIGNALS:
        return 'crash'
    if exit_code == 0:
        return 'accept'
    combined = ('%s\n%s' % (stdout or '', stderr or '')).lower()
    for indicator in CRASH_INDICATORS:
        if indicator in combined:
            return 'crash'
    for pattern in REJECT_PATTERNS:
        if pattern in combined:
            return 'reject'
    return 'reject'

def craft_test_battery(fmt: str, output_dir: str, crafter: Callable[[str, dict], None]) -> List[Dict[str, object]]:
    """Craft the full attack battery for ``fmt`` into ``output_dir``.

    ``fmt`` may be an alias.  Each spec is turned into a battery entry; the
    injected ``crafter`` materializes the file.  A crafter failure is recorded
    on the entry (``file_path`` set to ``None`` plus a ``craft_error``) rather
    than aborting the battery.

    Raises ``ValueError`` for a format that has no attack specs.
    """
    canonical = FORMAT_ALIASES.get(fmt, fmt)
    if canonical not in ATTACK_SPECS:
        raise ValueError('no attack specs for format: %r' % (fmt,))
    battery: List[Dict[str, object]] = []
    for spec in ATTACK_SPECS[canonical]:
        attack_type = spec['attack_type']
        ext = spec.get('ext', '')
        file_path = os.path.join(output_dir, '%s%s' % (attack_type, ext))
        entry: Dict[str, object] = {'format': canonical, 'attack_type': attack_type, 'file_path': file_path, 'cwe': spec['cwe'], 'description': spec['description']}
        try:
            crafter(file_path, spec)
        except Exception as exc:
            entry['file_path'] = None
            entry['craft_error'] = '%s: %s' % (type(exc).__name__, exc)
        battery.append(entry)
    return battery

def test_file_against_parser(file_path: str, fmt: str, runner: Callable[[str, str], Tuple[int, str, str, bool]]) -> Dict[str, object]:
    """Run one crafted ``file_path`` against the parser for ``fmt``.

    Returns a dict keyed by ``TEST_RESULT_FIELDS``.  A missing parser command
    or a missing parser module is an infrastructure *error* (not a parser
    verdict); everything else flows through :func:`_classify_result`.
    """
    canonical = FORMAT_ALIASES.get(fmt, fmt)
    if canonical not in PARSER_COMMANDS:
        return {'result': 'error', 'exit_code': -1, 'stdout': '', 'stderr': 'no parser command for format: %r' % (fmt,), 'exception_type': 'ValueError', 'time_s': 0.0}
    command = PARSER_COMMANDS[canonical].format(file=file_path)
    exit_code, stdout, stderr, timed_out = runner(command, file_path)
    lowered = ('%s\n%s' % (stdout or '', stderr or '')).lower()
    if 'modulenotfounderror' in lowered or 'no module named' in lowered:
        return {'result': 'error', 'exit_code': exit_code, 'stdout': stdout, 'stderr': stderr, 'exception_type': 'ModuleNotFoundError', 'time_s': 0.0}
    result = _classify_result(exit_code, stdout, stderr, timed_out)
    return {'result': result, 'exit_code': exit_code, 'stdout': stdout, 'stderr': stderr, 'exception_type': None, 'time_s': 0.0}
test_file_against_parser.__test__ = False

def score_format(fmt: str, output_path: Optional[str], cycle: int, round_num: int, crafter: Callable[[str, dict], None], runner: Callable[[str, str], Tuple[int, str, str, bool]], parser_version: str='unknown', timestamp: str='1970-01-01T00:00:00+00:00') -> Dict[str, object]:
    """Craft, run, and aggregate the full battery for a single format.

    The acceptance rate is computed over *testable* attacks only (those that
    crafted successfully); craft/infrastructure errors are excluded from the
    denominator.  If ``output_path`` is given the score is also written there
    as JSON.
    """
    canonical = FORMAT_ALIASES.get(fmt, fmt)
    if output_path:
        work_dir = os.path.dirname(os.path.abspath(output_path)) or '.'
    else:
        work_dir = os.path.join(tempfile.gettempdir(), 'mff_%s_%s_%s' % (canonical, cycle, round_num))
    os.makedirs(work_dir, exist_ok=True)
    battery = craft_test_battery(canonical, work_dir, crafter)
    results: Dict[str, int] = {kind: 0 for kind in RESULT_KINDS}
    attacks: List[Dict[str, object]] = []
    for entry in battery:
        if entry.get('file_path') is None:
            test_result = {'result': 'error', 'exit_code': -1, 'stdout': '', 'stderr': str(entry.get('craft_error', 'craft failed')), 'exception_type': 'CraftError', 'time_s': 0.0}
        else:
            test_result = test_file_against_parser(str(entry['file_path']), canonical, runner)
        kind = test_result['result']
        if kind not in results:
            kind = 'error'
        results[kind] += 1
        record = dict(entry)
        record.update(test_result)
        attacks.append(record)
    total_attacks = len(battery)
    testable = total_attacks - results['error']
    if testable > 0:
        acceptance_rate = round(results['accept'] / testable, 3)
    else:
        acceptance_rate = 0.0
    score: Dict[str, object] = {'format': canonical, 'cycle': cycle, 'round': round_num, 'timestamp': timestamp, 'total_attacks': total_attacks, 'results': results, 'acceptance_rate': acceptance_rate, 'parser_version': parser_version, 'attacks': attacks}
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as fh:
            json.dump(score, fh, indent=2)
    return score

def score_all_formats(output_dir: str, cycle: int, round_num: int, crafter: Callable[[str, dict], None], runner: Callable[[str, str], Tuple[int, str, str, bool]], formats: Optional[List[str]]=None, timestamp: str='1970-01-01T00:00:00+00:00', parser_version: str='unknown') -> List[Dict[str, object]]:
    """Score every requested format, returning one score per format in order.

    ``formats`` defaults to all formats that own attack specs.  Each format's
    score is also written to ``<output_dir>/<format>_mff_score.json``.
    """
    if formats is None:
        formats = list(ATTACK_SPECS.keys())
    os.makedirs(output_dir, exist_ok=True)
    scores: List[Dict[str, object]] = []
    for fmt in formats:
        canonical = FORMAT_ALIASES.get(fmt, fmt)
        out_path = os.path.join(output_dir, '%s_mff_score.json' % (canonical,))
        scores.append(score_format(fmt, out_path, cycle=cycle, round_num=round_num, crafter=crafter, runner=runner, parser_version=parser_version, timestamp=timestamp))
    return scores

def make_mock_crafter(fail_for: Tuple[str, ...]=()) -> Callable[[str, dict], None]:
    """Return a crafter that touches the target file.

    Attack types listed in ``fail_for`` raise instead of crafting, simulating a
    craft failure.
    """
    failing = set(fail_for)

    def crafter(file_path: str, spec: dict) -> None:
        if spec.get('attack_type') in failing:
            raise RuntimeError('craft failed for %r' % (spec.get('attack_type'),))
        with open(file_path, 'wb') as fh:
            fh.write(b'\x00')
    return crafter

def make_mock_runner(exit_code: int=0, stdout: str='', stderr: str='', time_s: float=0.0, timed_out: bool=False) -> Callable[[str, str], Tuple[int, str, str, bool]]:
    """Return a runner that always yields a fixed ``(exit_code, stdout, stderr,
    timed_out)`` tuple, regardless of command or file."""

    def runner(command: str, file_path: str) -> Tuple[int, str, str, bool]:
        return (exit_code, stdout, stderr, timed_out)
    return runner

def make_scripted_runner(script: Dict[str, Tuple[int, str, str, bool]], default: Tuple[int, str, str, bool]=(0, '', '', False)) -> Callable[[str, str], Tuple[int, str, str, bool]]:
    """Return a runner that dispatches on ``file_path``.

    ``script`` maps a file path to its ``(exit_code, stdout, stderr,
    timed_out)`` result; unlisted paths fall back to ``default``.
    """
    table = dict(script)

    def runner(command: str, file_path: str) -> Tuple[int, str, str, bool]:
        return table.get(file_path, default)
    return runner