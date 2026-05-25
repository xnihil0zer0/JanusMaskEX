"""ORACLE: the merged==original equivalence gate (the NEW correctness proof).

The rebuild loop's third gate. After Claude==Gemini (existing diff_fuzzer) and
AST-merge land a reconstructed body, the oracle feeds the stashed ORIGINAL
module as side-B into the SAME differential fuzzer and asserts the
reconstructed unit is behaviorally equivalent to the original over fuzzed
inputs. This is what makes the rebuild a faithful replication rather than a
plausible reimplementation.

Run as a CLI from a unit's ``verification_command`` (cwd = output repo,
``PYTHONPATH`` pointed at the parent JanusMask so ``harness`` imports):

    python -m harness.rebuild.oracle --target mathlib.py \
        --original /abs/stash/mathlib.py.orig --unit gcd --config /abs/config.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def check_equivalence(
    reconstructed_source: str, original_source: str, unit: str, config: dict
) -> tuple[bool, str]:
    """Return (equivalent, message) for reconstructed-vs-original over fuzzed inputs.

    ``unit`` is the top-level function name to fuzz. A fuzz error (e.g. the
    target function is undiscoverable) is reported as NOT equivalent so the
    gate fails loud rather than silently passing.
    """
    from harness.diff_fuzzer import differential_fuzz

    result = differential_fuzz(
        reconstructed_source, original_source, unit, config, session_id=f'oracle_{unit}'
    )
    if getattr(result, 'error', None):
        return False, f'fuzz_error: {result.error}'
    equivalent = bool(result.equivalent)
    return equivalent, 'equivalent' if equivalent else 'divergent'


def _load_config(config_path: str | None) -> dict:
    if not config_path:
        return {}
    from harness.orchestrator import load_config

    return load_config(Path(config_path))


def main(argv: list[str] | None = None) -> int:
    # Bootstrap: when invoked as a file (python <parent>/harness/rebuild/oracle.py)
    # from inside the output repo, the output repo's own ``harness`` package (if
    # any, e.g. JR) is NOT on sys.path and the parent JanusMask root IS, so
    # ``harness.diff_fuzzer`` resolves to the parent oracle machinery rather than
    # the reconstructed replicant. Prepending parents[2] is idempotent.
    _parent = str(Path(__file__).resolve().parents[2])
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
    p = argparse.ArgumentParser(description='Rebuild oracle: merged==original equivalence gate.')
    p.add_argument('--target', required=True, help='Reconstructed module file (in the output repo).')
    p.add_argument('--original', required=True, help='Stashed original module (the oracle).')
    p.add_argument('--unit', required=True, help='Top-level function name to fuzz.')
    p.add_argument('--config', default=None, help='Path to harness/config.yaml (parent repo).')
    p.add_argument('--str-ascii', dest='str_ascii', action='store_true',
                   help='REBUILD-SCOPED: fuzz str params over the ASCII-printable alphabet '
                        'only (closes the unicode-ambiguity false-divergence frontier for '
                        'str transforms; W1/C9.14). Default: full unicode alphabet.')
    args = p.parse_args(argv)
    recon = Path(args.target).read_text(encoding='utf-8')
    orig = Path(args.original).read_text(encoding='utf-8')
    config = _load_config(args.config)
    if args.str_ascii:
        config = {**config, 'rebuild': {**config.get('rebuild', {}), 'fuzz_str_ascii': True}}
    ok, msg = check_equivalence(recon, orig, args.unit, config)
    sys.stdout.write(f'oracle[{args.unit}]: {msg}\n')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
