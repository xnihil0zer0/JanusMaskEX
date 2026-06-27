"""L0 artifact contracts for NobleGreed v2.

Defines the deterministic, stdlib-only data model shared across the
pipeline: the :class:`Finding`, :class:`PoC`, and :class:`LiveTestReport`
dataclasses plus the ``SEVERITIES`` and ``VERDICTS`` constants. Each class
round-trips losslessly through ``to_dict``/``from_dict`` and exposes a
``validate`` method enforcing its invariants.
"""
from dataclasses import dataclass, field, fields
from typing import List, Optional
SEVERITIES = ('low', 'medium', 'high', 'critical')
VERDICTS = ('confirmed', 'refuted', 'error', 'inconclusive')

@dataclass
class Bounty:
    """A sourced bounty candidate from a vulnerability platform."""
    platform: str
    repo_url: str
    package: str
    cwe: str
    advisory_id: str
    tier: str
    observed_payout: int = 0
    max_paid: int = 0
    submissions: int = 0
    eligible: bool = False
    fp_risk: float = 0.0
    discovered_at: str = ''

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> 'Bounty':
        return cls(**{f.name: d[f.name] for f in fields(cls) if f.name in d})

    def validate(self) -> None:
        for field_name in ('platform', 'repo_url', 'package', 'cwe'):
            if not _is_nonempty_str(getattr(self, field_name)):
                raise ValueError(f'{field_name} must be a non-empty str')
        for field_name in ('observed_payout', 'max_paid', 'submissions'):
            if getattr(self, field_name) < 0:
                raise ValueError(f'{field_name} must not be negative')
        if not 0.0 <= self.fp_risk <= 1.0:
            raise ValueError('fp_risk must be within [0.0, 1.0]')

@dataclass
class Target:
    """An acquired target repository ready for analysis."""
    repo_url: str
    repo_root: str
    pinned_commit: str
    language: str
    loc: int = 0
    cloned_at: str = ''

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> 'Target':
        return cls(**{f.name: d[f.name] for f in fields(cls) if f.name in d})

    def validate(self) -> None:
        for field_name in ('repo_url', 'repo_root', 'pinned_commit', 'language'):
            if not _is_nonempty_str(getattr(self, field_name)):
                raise ValueError(f'{field_name} must be a non-empty str')
        if self.loc < 0:
            raise ValueError('loc must not be negative')
def _is_nonempty_str(value: object) -> bool:
    """Return True iff ``value`` is a non-empty ``str``."""
    return isinstance(value, str) and value != ''

@dataclass
class Finding:
    id: str
    target: str
    category: str
    severity: str
    title: str
    description: str
    evidence: List = field(default_factory=list)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> 'Finding':
        return cls(id=d['id'], target=d['target'], category=d['category'], severity=d['severity'], title=d['title'], description=d['description'], evidence=d['evidence'] if 'evidence' in d else [])

    def validate(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f'severity must be one of {SEVERITIES}, got {self.severity!r}')
        for name in ('id', 'target', 'category', 'title'):
            if not _is_nonempty_str(getattr(self, name)):
                raise ValueError(f'{name} must be a non-empty str')

@dataclass
class PoC:
    finding_id: str
    language: str
    code: str
    entrypoint: str

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> 'PoC':
        return cls(finding_id=d['finding_id'], language=d['language'], code=d['code'], entrypoint=d['entrypoint'])

    def validate(self) -> None:
        for name in ('finding_id', 'language', 'code', 'entrypoint'):
            if not _is_nonempty_str(getattr(self, name)):
                raise ValueError(f'{name} must be a non-empty str')

@dataclass
class LiveTestReport:
    poc_finding_id: str
    verdict: str
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration_ms: int

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> 'LiveTestReport':
        return cls(poc_finding_id=d['poc_finding_id'], verdict=d['verdict'], exit_code=d['exit_code'], stdout=d['stdout'], stderr=d['stderr'], duration_ms=d['duration_ms'])

    def validate(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f'verdict must be one of {VERDICTS}, got {self.verdict!r}')
        if self.duration_ms < 0:
            raise ValueError('duration_ms must be >= 0')
        if not _is_nonempty_str(self.poc_finding_id):
            raise ValueError('poc_finding_id must be a non-empty str')