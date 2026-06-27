"""NobleGreedv2 knowledge-graph data model (``ngv2.kg_schema``).

A pure, deterministic schema for the NobleGreedv2 knowledge graph:
controlled-vocabulary string ``Enum``s plus validated domain models
(:class:`Source`, :class:`Entity`, :class:`Fact`, :class:`Relation`,
:class:`TaskRecord`, :class:`CycleReport`).

The oracle exercises a pydantic-v2 style surface (``model_dump`` /
``model_validate``, validation on construction, value equality), but the
verification environment is stdlib-only, so this module re-expresses that
contract with :mod:`enum`, :mod:`typing`, and a small hand-written model
base built on plain dicts. No clock / network / randomness is used:
timestamp fields default to ``None`` rather than reading the wall clock,
so the contract is fully reproducible.
"""
from __future__ import annotations
import enum
from typing import Any, Callable, Dict, List, Optional

class EntityType(str, enum.Enum):
    """Kinds of node that can live in the knowledge graph."""
    PLATFORM = 'platform'
    SERVICE = 'service'
    SKILL = 'skill'
    OPPORTUNITY = 'opportunity'
    TOOL = 'tool'
    CLIENT = 'client'
    MARKET = 'market'

class OpportunityStatus(str, enum.Enum):
    """Lifecycle states for a tracked opportunity."""
    DISCOVERED = 'discovered'
    QUALIFIED = 'qualified'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    REJECTED = 'rejected'
    EXPIRED = 'expired'

class ServiceTier(str, enum.Enum):
    """Relative value tier of a service."""
    FREE = 'free'
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'

class ConfidenceLevel(str, enum.Enum):
    """Qualitative confidence buckets."""
    VERIFIED = 'verified'
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
_MISSING = object()

class _Field:
    """Declarative description of a single model field.

    Mirrors just enough of pydantic's per-field behaviour: a default (or a
    default *factory* for mutable containers), an optional coercion applied
    to non-``None`` inputs, and an optional validator that raises on bad
    values.
    """
    __slots__ = ('default', 'default_factory', 'coerce', 'check')

    def __init__(self, default: Any=_MISSING, default_factory: Optional[Callable[[], Any]]=None, coerce: Optional[Callable[[Any], Any]]=None, check: Optional[Callable[[Any], None]]=None) -> None:
        self.default = default
        self.default_factory = default_factory
        self.coerce = coerce
        self.check = check

    @property
    def required(self) -> bool:
        return self.default is _MISSING and self.default_factory is None

    def make_default(self) -> Any:
        if self.default_factory is not None:
            return self.default_factory()
        return self.default

    def process(self, value: Any) -> Any:
        if self.coerce is not None and value is not None:
            value = self.coerce(value)
        if self.check is not None:
            self.check(value)
        return value

def _dump_value(value: Any) -> Any:
    """Recursively convert a stored value into plain JSON-friendly data."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, list):
        return [_dump_value(item) for item in value]
    if isinstance(value, dict):
        return {ident: _dump_value(item) for ident, item in value.items()}
    return value

class BaseModel:
    """Minimal pydantic-v2-flavoured base model over a field spec.

    Subclasses declare ``__fields__`` mapping field name -> :class:`_Field`.
    Construction validates and coerces every field; mutable defaults are
    produced fresh per instance so they are never shared.
    """
    __fields__: Dict[str, _Field] = {}

    def __init__(self, **data: Any) -> None:
        fields = type(self).__fields__
        for field_name, field in fields.items():
            if field_name in data:
                raw = data[field_name]
            elif field.required:
                raise ValueError('%s: missing required field %r' % (type(self).__name__, field_name))
            else:
                raw = field.make_default()
            setattr(self, field_name, field.process(raw))

    def model_dump(self) -> Dict[str, Any]:
        return {field_name: _dump_value(getattr(self, field_name)) for field_name in type(self).__fields__}

    @classmethod
    def model_validate(cls, data: Dict[str, Any]) -> 'BaseModel':
        if isinstance(data, cls):
            return data
        return cls(**dict(data))

    def __eq__(self, other: Any) -> bool:
        if type(self) is not type(other):
            return NotImplemented
        return all((getattr(self, field_name) == getattr(other, field_name) for field_name in type(self).__fields__))
    __hash__ = None

    def __repr__(self) -> str:
        inner = ', '.join(('%s=%r' % (field_name, getattr(self, field_name)) for field_name in type(self).__fields__))
        return '%s(%s)' % (type(self).__name__, inner)

def _coerce_entity_type(value: Any) -> EntityType:
    return value if isinstance(value, EntityType) else EntityType(value)

def _make_range_check(low: Optional[float]=None, high: Optional[float]=None):

    def _check(value: Any) -> None:
        if value is None:
            return
        if low is not None and value < low:
            raise ValueError('value %r below minimum %r' % (value, low))
        if high is not None and value > high:
            raise ValueError('value %r above maximum %r' % (value, high))
    return _check

def _make_prefix_check(prefix: str):

    def _check(value: Any) -> None:
        if not isinstance(value, str) or ':' not in value:
            raise ValueError("id %r must be of the form '%s:<slug>'" % (value, prefix))
        if value.split(':', 1)[0] != prefix:
            raise ValueError('id %r must use the %r prefix' % (value, prefix))
    return _check

def _check_entity_id(value: Any) -> None:
    if not isinstance(value, str) or ':' not in value:
        raise ValueError("entity id %r must be of the form '<type>:<slug>'" % (value,))
    prefix = value.split(':', 1)[0]
    allowed = {member.value for member in EntityType}
    if prefix not in allowed:
        raise ValueError('entity id prefix %r is not a valid EntityType' % (prefix,))

def _coerce_sources(value: Any) -> List['Source']:
    items: List[Source] = []
    for item in value:
        if isinstance(item, Source):
            items.append(item)
        else:
            items.append(Source(**dict(item)))
    return items

class Source(BaseModel):
    """Provenance for a fact, entity, or relation."""
    __fields__ = {'ref': _Field(), 'retrieved_at': _Field(default=None), 'quote': _Field(default=None)}
    ref: str
    retrieved_at: Optional[str]
    quote: Optional[str]

class Entity(BaseModel):
    """A typed node in the knowledge graph."""
    __fields__ = {'id': _Field(check=_check_entity_id), 'name': _Field(), 'type': _Field(coerce=_coerce_entity_type), 'description': _Field(), 'aliases': _Field(default_factory=list), 'attributes': _Field(default_factory=dict), 'sources': _Field(default_factory=list, coerce=_coerce_sources), 'confidence': _Field(default=0.8, coerce=float, check=_make_range_check(0.0, 1.0)), 'created_at': _Field(default=None), 'updated_at': _Field(default=None)}
    id: str
    name: str
    type: EntityType
    description: str
    aliases: List[str]
    attributes: Dict[str, Any]
    sources: List[Source]
    confidence: float
    created_at: Optional[str]
    updated_at: Optional[str]

    @property
    def entity_type(self) -> str:
        """The type prefix derived from the entity id."""
        return self.id.split(':', 1)[0]

class Fact(BaseModel):
    """An atomic subject-predicate-object assertion."""
    __fields__ = {'id': _Field(check=_make_prefix_check('fact')), 'subject': _Field(), 'predicate': _Field(), 'object': _Field(), 'confidence': _Field(default=0.8, coerce=float, check=_make_range_check(0.0, 1.0)), 'sources': _Field(default_factory=list, coerce=_coerce_sources), 'discovered_at': _Field(default=None)}
    id: str
    subject: str
    predicate: str
    object: str
    confidence: float
    sources: List[Source]
    discovered_at: Optional[str]

class Relation(BaseModel):
    """A weighted, typed edge between two entities."""
    __fields__ = {'id': _Field(check=_make_prefix_check('rel')), 'subject': _Field(), 'predicate': _Field(), 'object': _Field(), 'weight': _Field(default=1.0, coerce=float, check=_make_range_check(0.0, None)), 'description': _Field(default=None), 'sources': _Field(default_factory=list, coerce=_coerce_sources)}
    id: str
    subject: str
    predicate: str
    object: str
    weight: float
    description: Optional[str]
    sources: List[Source]

class TaskRecord(BaseModel):
    """Outcome record for a single executed task."""
    __fields__ = {'id': _Field(), 'service_type': _Field(), 'opportunity_id': _Field(default=None), 'status': _Field(default='pending'), 'started_at': _Field(default=None), 'completed_at': _Field(default=None), 'duration_seconds': _Field(default=0.0), 'revenue_usd': _Field(default=0.0), 'cost_usd': _Field(default=0.0), 'quality_score': _Field(default=None), 'notes': _Field(default='')}
    id: str
    service_type: str
    opportunity_id: Optional[str]
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    duration_seconds: float
    revenue_usd: float
    cost_usd: float
    quality_score: Optional[float]
    notes: str

class CycleReport(BaseModel):
    """Aggregate summary of one autonomy cycle."""
    __fields__ = {'cycle_number': _Field(), 'started_at': _Field(default=None), 'completed_at': _Field(default=None), 'phase_durations_s': _Field(default_factory=dict), 'opportunities_found': _Field(default=0), 'tasks_completed': _Field(default=0), 'revenue_usd': _Field(default=0.0), 'roi_per_hour': _Field(default=0.0), 'key_learnings': _Field(default_factory=list), 'next_priorities': _Field(default_factory=list)}
    cycle_number: int
    started_at: Optional[str]
    completed_at: Optional[str]
    phase_durations_s: Dict[str, float]
    opportunities_found: int
    tasks_completed: int
    revenue_usd: float
    roi_per_hour: float
    key_learnings: List[str]
    next_priorities: List[str]
__all__ = ['EntityType', 'OpportunityStatus', 'ServiceTier', 'ConfidenceLevel', 'Source', 'Entity', 'Fact', 'Relation', 'TaskRecord', 'CycleReport']