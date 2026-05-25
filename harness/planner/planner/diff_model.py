import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Tuple, Any, List

class DiffKind(str, Enum):
    claude_only = "claude_only"
    gemini_only = "gemini_only"
    convergent = "convergent"
    divergent = "divergent"
    ambiguous_match = "ambiguous_match"

class FieldKind(str, Enum):
    scope = "scope"
    priority = "priority"
    tests = "tests"
    dependencies = "dependencies"
    files_touched = "files_touched"
    edge_cases = "edge_cases"
    non_goals = "non_goals"

@dataclass(frozen=True)
class DiffItem:
    kind: DiffKind
    claude_task: Optional[dict[str, Any]] = None
    gemini_task: Optional[dict[str, Any]] = None
    field_divergences: Tuple[Tuple[FieldKind, Any, Any], ...] = field(default_factory=tuple)
    match_reason: Optional[str] = None
    candidate_near_miss: Optional[str] = None
    candidates: Optional[Tuple[Any, ...]] = None
    diff_item_id: str = field(init=False)

    def __post_init__(self):
        claude_task_id = self.claude_task.get("task_id", "") if self.claude_task else ""
        gemini_task_id = self.gemini_task.get("task_id", "") if self.gemini_task else ""
        
        # Canonicalize field divergences for hashing
        # Sorting by the FieldKind string value
        sorted_divergences = sorted(self.field_divergences, key=lambda x: x[0].value if hasattr(x[0], 'value') else str(x[0]))
        
        # Serialize the tuple to a JSON string for hashing
        # Need to ensure we sort keys and use stable serialization
        payload = [
            self.kind.value if hasattr(self.kind, 'value') else str(self.kind),
            claude_task_id,
            gemini_task_id,
            sorted_divergences,
            self.candidates
        ]
        
        def _serialize(obj):
            if isinstance(obj, Enum):
                return obj.value
            return obj
            
        payload_str = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=_serialize)
        
        # Calculate SHA1
        object.__setattr__(
            self, 
            'diff_item_id', 
            hashlib.sha1(payload_str.encode('utf-8')).hexdigest()
        )

@dataclass(frozen=True)
class PlanDiff:
    items: Tuple[DiffItem, ...] = field(default_factory=tuple)

    def to_json(self) -> str:
        def custom_encoder(obj):
            if isinstance(obj, Enum):
                return obj.value
            return obj
            
        data = [asdict(item) for item in self.items]
        # Force LF newlines by replacing any potential CRLF, though dumps uses LF natively
        return json.dumps({"items": data}, sort_keys=True, indent=2, default=custom_encoder, separators=(',', ': '))

    @classmethod
    def from_json(cls, json_str: str) -> 'PlanDiff':
        data = json.loads(json_str)
        items_data = data.get("items", [])
        
        parsed_items = []
        for item_data in items_data:
            kind = DiffKind(item_data["kind"])
            claude_task = item_data.get("claude_task")
            gemini_task = item_data.get("gemini_task")
            
            field_divergences = []
            for div in item_data.get("field_divergences", []):
                field_divergences.append((FieldKind(div[0]), div[1], div[2]))
            
            match_reason = item_data.get("match_reason")
            candidate_near_miss = item_data.get("candidate_near_miss")
            candidates = item_data.get("candidates")
            if candidates is not None:
                candidates = tuple(candidates)
                
            parsed_items.append(DiffItem(
                kind=kind,
                claude_task=claude_task,
                gemini_task=gemini_task,
                field_divergences=tuple(field_divergences),
                match_reason=match_reason,
                candidate_near_miss=candidate_near_miss,
                candidates=candidates
            ))
            
        return cls(items=tuple(parsed_items))
