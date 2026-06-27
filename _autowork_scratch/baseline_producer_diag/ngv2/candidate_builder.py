"""Per-(repo, CWE) candidate builder.

Builds one plain candidate dict per (repo, CWE) combination present in the
corpus stats. Each candidate carries the repo and cwe identifiers plus that
repo's per-CWE prior-submission saturation -- the fields the downstream
selection contract (``rank_candidates``) consumes. CWE classes whose pipeline
capability is ``'none'`` are suppressed until their detector lands; capable
classes are emitted even when the repo has zero prior submissions.

Pure and deterministic: no I/O, clock, or randomness. Iteration order is fixed
by sorting the (repo, cwe) keys so identical inputs always yield identical
output.
"""
from ngv2.bounty_corpus_stats import CorpusStats

def build_candidates(stats: CorpusStats) -> list[dict]:
    """Return one candidate dict per (repo, CWE) pair in ``stats.saturation``.

    A candidate is emitted for a (repo, cwe) pair only when that CWE's
    ``pipeline_capability`` is not ``'none'``. Each candidate carries:

    * ``repo``        -- the "owner/repo" identifier string,
    * ``cwe``         -- the CWE id string,
    * ``submissions`` -- the per-CWE saturation as an int (0 when missing),
    * ``saturation``  -- the per-CWE saturation as a float (0.0 when missing).

    Edge cases: empty saturation yields ``[]``; a pair whose saturation entry
    is missing still defaults to 0.0 / 0 rather than raising.
    """
    capability = stats.pipeline_capability
    candidates: list[dict] = []
    for repo, cwe in sorted(stats.saturation):
        if capability.get(cwe) == 'none':
            continue
        saturation = float(stats.saturation.get((repo, cwe), 0.0))
        candidates.append({'repo': repo, 'cwe': cwe, 'submissions': int(saturation), 'saturation': saturation})
    return candidates