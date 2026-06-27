"""CWE -> sink-pattern registry plus learned per-target weighting.

This leaf provides two things consumed by the hunter:

* ``SINK_PATTERNS`` -- a data-driven map from CWE id to the concrete sink
  patterns/regexes that mark a candidate for that vulnerability class.
* ``compute_weights`` -- a deterministic per-repo weighting over the sibling
  ``CorpusStats`` contract so the hunter scans high-value, in-demand, and still
  un-saturated CWE lanes first.

The weight for each CWE factorises explicitly as::

    weight = demand x pipeline_capability x novelty

where ``demand`` is the corpus expected value for the repo,
``pipeline_capability`` is a numeric multiplier coerced from the capability
label (a CWE whose detector has not landed -- label ``"none"`` -- weighs 0),
and ``novelty`` is ``max(0.0, 1 - saturation)`` so a saturated lane collapses
to zero. Pure: no I/O, no clock, deterministic over the injected stats.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ngv2.bounty_corpus_stats import CorpusStats
SINK_PATTERNS: dict[str, list[str]] = {'CWE-502': ['pickle\\.loads?\\s*\\(', 'cPickle\\.loads?\\s*\\(', 'marshal\\.loads?\\s*\\(', 'yaml\\.load\\s*\\(', 'yaml\\.unsafe_load\\s*\\(', 'torch\\.load\\s*\\(', 'joblib\\.load\\s*\\(', 'dill\\.loads?\\s*\\('], 'CWE-78': ['os\\.system\\s*\\(', 'subprocess\\.(?:call|run|Popen|check_output)\\s*\\(', 'os\\.popen\\s*\\(', 'commands\\.getoutput\\s*\\(', '\\bshell\\s*=\\s*True\\b'], 'CWE-918': ['requests\\.(?:get|post|put|delete|head|patch)\\s*\\(', 'urllib\\.request\\.urlopen\\s*\\(', 'urllib2\\.urlopen\\s*\\(', 'httpx\\.(?:get|post|Client)\\s*\\(', 'aiohttp\\.ClientSession\\s*\\('], 'CWE-22': ['open\\s*\\(', 'os\\.path\\.join\\s*\\(', 'send_file\\s*\\(', 'send_from_directory\\s*\\(', 'shutil\\.(?:copy|move|rmtree)\\s*\\(']}
_CAPABILITY_MULTIPLIER: dict[str, float] = {'none': 0.0, 'scannable': 0.5, 'scannable+confirmable': 1.0}
_DEFAULT_CAPABILITY_MULTIPLIER: float = 0.0

def _capability_multiplier(label: str | None) -> float:
    """Coerce a pipeline-capability label to a deterministic multiplier."""
    if not label:
        return _DEFAULT_CAPABILITY_MULTIPLIER
    return _CAPABILITY_MULTIPLIER.get(label, _DEFAULT_CAPABILITY_MULTIPLIER)

def compute_weights(stats: 'CorpusStats', repo: str) -> dict[str, float]:
    """Return a per-CWE scan weight for ``repo`` over the injected stats.

    weight[cwe] = demand x pipeline_capability x novelty, with
    ``demand`` = ``stats.expected_value[repo]`` (0.0 if the repo is unknown),
    ``pipeline_capability`` coerced from ``stats.pipeline_capability[cwe]``,
    and ``novelty`` = ``max(0.0, 1 - stats.saturation[(repo, cwe)])`` (1.0 when
    no prior submissions are recorded). The returned keys are exactly the CWE
    keys present in ``SINK_PATTERNS`` and all values are floats >= 0.0.
    """
    demand = float(stats.expected_value.get(repo, 0.0))
    weights: dict[str, float] = {}
    for cwe in SINK_PATTERNS:
        capability = _capability_multiplier(stats.pipeline_capability.get(cwe))
        saturation = float(stats.saturation.get((repo, cwe), 0.0))
        novelty = max(0.0, 1.0 - saturation)
        weights[cwe] = float(demand * capability * novelty)
    return weights