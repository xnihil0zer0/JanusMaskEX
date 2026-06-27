"""Pure, deterministic run-state reconciliation for ngv2.

Legacy NobleGreed's ``state_sync`` globbed GraphMERT metric files and adversarial
score/evasion JSON off disk, then rewrote ``state.json`` under ``fcntl.flock``.
This clean-room module distils only the *durable* capability: reconcile an
in-memory run-state ``dict`` against external data that arrives through an
INJECTED ``sources`` mapping (the deterministic seam), idempotently, reporting
one human-readable change string per field actually brought into agreement.

The module is pure with respect to the environment: it performs no clock reads,
no network, no subprocess, no randomness and no file I/O. The only observable
effects are the in-place mutation of the passed-in ``state`` argument and the
returned list of change strings. The injected ``sources`` mapping is never
mutated.

stdlib only; imports no third-party package and no sibling ngv2 leaf.
"""
from typing import Any, List, Mapping, MutableMapping
_SECTION_SPEC: Mapping[str, Any] = {'metrics_section': 'evaluation_metrics', 'adversarial_section': 'adversarial', 'graphmert_inputs': ('training', 'integration'), 'adversarial_inputs': ('scores', 'root_causes', 'evasions')}
EVALUATION_METRICS_KEY = _SECTION_SPEC['metrics_section']
ADVERSARIAL_KEY = _SECTION_SPEC['adversarial_section']
GRAPHMERT_SOURCE_KEYS = _SECTION_SPEC['graphmert_inputs']
ADVERSARIAL_SOURCE_KEYS = _SECTION_SPEC['adversarial_inputs']
_ROUND_PLACES = 3

def _apply_updates(section: MutableMapping[str, Any], section_label: str, updates: List[Any]) -> List[str]:
    """Apply ``(field, value)`` pairs to ``section`` in order, in place.

    A change string is emitted only for fields whose stored value actually
    differs from the new value, which is what makes a re-run a no-op.
    """
    changes: List[str] = []
    for field_name, value in updates:
        if section.get(field_name) != value:
            previous = section.get(field_name)
            section[field_name] = value
            changes.append('{0}.{1}: {2} -> {3}'.format(section_label, field_name, previous, value))
    return changes

def sync_graphmert(state: MutableMapping[str, Any], sources: Mapping[str, Any]) -> List[str]:
    """Reconcile GraphMERT evaluation metrics into ``state`` in place.

    Reads cross-validation ``f1``/``auc`` means, the training sample count and
    an optional integration accuracy from the injected ``sources`` mapping,
    writes the normalised values plus a human-readable ``graphmert_status`` line
    under ``state['evaluation_metrics']``, and returns one change string per
    field actually written. Missing fields are skipped without raising; an
    already-consistent state yields an empty list and is left unchanged.
    """
    training = sources.get('training') or {}
    integration = sources.get('integration') or {}
    updates: List[Any] = []
    f1_source = training.get('f1')
    if isinstance(f1_source, Mapping) and f1_source.get('mean') is not None:
        updates.append(('f1', round(f1_source['mean'], _ROUND_PLACES)))
    auc_source = training.get('auc')
    if isinstance(auc_source, Mapping) and auc_source.get('mean') is not None:
        updates.append(('auc', round(auc_source['mean'], _ROUND_PLACES)))
    data_stats = training.get('data_stats')
    if isinstance(data_stats, Mapping) and data_stats.get('n_samples') is not None:
        updates.append(('n_samples', data_stats['n_samples']))
    resolved = dict(updates)
    if 'f1' in resolved and 'auc' in resolved and ('n_samples' in resolved):
        status = '5-fold CV F1={0}, AUC={1}, n={2}'.format(resolved['f1'], resolved['auc'], resolved['n_samples'])
        accuracy = integration.get('accuracy')
        if accuracy is not None:
            status += ', integration accuracy={0:.1f}%'.format(accuracy * 100)
        updates.append(('graphmert_status', status))
    if not updates:
        return []
    metrics = state.setdefault(EVALUATION_METRICS_KEY, {})
    return _apply_updates(metrics, EVALUATION_METRICS_KEY, updates)

def sync_adversarial(state: MutableMapping[str, Any], sources: Mapping[str, Any]) -> List[str]:
    """Reconcile adversarial-evaluation aggregates into ``state`` in place.

    Aggregates injection/detection/evasion counts across the injected score
    records, counts written root-cause rules, builds the rounded evasion-rate
    trend (dropping ``None`` rates), records the latest positive cycle, and
    returns one change string per field actually written. The injected
    ``sources`` mapping is never mutated; a re-run on consistent state returns
    an empty list.
    """
    updates: List[Any] = []
    if 'scores' in sources:
        scores = sources.get('scores') or []
        total_injections = sum((record.get('total_injections', 0) for record in scores))
        detected_count = sum((record.get('detected_count', 0) for record in scores))
        evaded_count = sum((record.get('evaded_count', 0) for record in scores))
        updates.append(('total_injections', total_injections))
        updates.append(('detected_count', detected_count))
        updates.append(('evaded_count', evaded_count))
    if 'root_causes' in sources:
        root_causes = sources.get('root_causes') or []
        updates.append(('rules_written', len(root_causes)))
    if 'evasions' in sources:
        evasions = sources.get('evasions') or []
        trend = [round(record['evasion_rate'], _ROUND_PLACES) for record in evasions if record.get('evasion_rate') is not None]
        if trend:
            updates.append(('evasion_rate_trend', trend))
            updates.append(('evasion_rate', trend[-1]))
    cycles: List[Any] = []
    for input_label in ('scores', 'evasions'):
        for record in sources.get(input_label) or []:
            cycle = record.get('cycle')
            if isinstance(cycle, (int, float)) and (not isinstance(cycle, bool)) and (cycle > 0):
                cycles.append(cycle)
    if cycles:
        updates.append(('last_cycle', max(cycles)))
    if not updates:
        return []
    adversarial = state.setdefault(ADVERSARIAL_KEY, {})
    return _apply_updates(adversarial, ADVERSARIAL_KEY, updates)