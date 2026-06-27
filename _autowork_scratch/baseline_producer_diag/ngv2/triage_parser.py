"""Parse an ng-triage debate result into a normalized verdict dict.

Pure, deterministic, standard-library only. This module intentionally
avoids importing ``ngv2.verdict`` or any other Epic-3 leaf module, and
performs no file or network I/O.
"""
_VERDICT_LABELS = {'SUBMIT': 'TP', 'REJECT': 'FP', 'NEEDS_INVESTIGATION': 'FP'}

def _band_confidence(value: float) -> str:
    """Map a numeric confidence to a HIGH/MEDIUM/LOW band."""
    if value >= 0.7:
        return 'HIGH'
    if value >= 0.4:
        return 'MEDIUM'
    return 'LOW'

def parse_triage(debate: dict) -> dict:
    """Map an ng-triage debate JSON structure to a normalized verdict dict.

    Args:
        debate: A debate-result mapping containing ``finding_id``,
            ``final_verdict``, ``final_confidence`` and an optional
            ``reasoning`` key.

    Returns:
        A dict shaped as
        ``{'finding_id': str, 'label': str, 'confidence': str, 'reasoning': str}``.
    """
    finding_id = debate['finding_id']
    final_verdict = debate['final_verdict']
    final_confidence = debate['final_confidence']
    reasoning = debate.get('reasoning', '')
    label = _VERDICT_LABELS[final_verdict]
    confidence = _band_confidence(final_confidence)
    return {'finding_id': finding_id, 'label': label, 'confidence': confidence, 'reasoning': reasoning}