"""ngv2.kg_store — deterministic dual-backend knowledge store.

KGStore is a SQLite-backed (structural) knowledge graph for the NobleGreed
economic domain: entities, facts, relations, and task/revenue records. The
second backend (legacy ChromaDB semantic search) is replaced by a pure,
deterministic INJECTED SEAM: KGStore takes an ``embedder`` callable
(``str -> tuple[float, ...]``) and computes cosine similarity in Python, so
``find_similar_*`` are fully deterministic with no third-party vector DB.

The module is standard-library only (``sqlite3``, ``math``, ``json``) and makes
no network / clock / subprocess calls in its tested surfaces. Entity / Fact /
Relation / task arguments are duck-typed: any object exposing the required
attributes works.
"""
from __future__ import annotations
import json
import math
import sqlite3
from typing import Any, Callable, Dict, List, Optional, Tuple
ENTITY_COLUMNS: Tuple[str, ...] = ('id', 'name', 'type', 'description', 'attributes_json', 'sources_json', 'confidence', 'created_at', 'updated_at')
REVENUE_SUMMARY_KEYS: Tuple[str, ...] = ('total_tasks', 'completed', 'total_revenue', 'avg_duration', 'avg_quality')
STATS_KEYS: Tuple[str, ...] = ('entities', 'facts', 'relations')

def make_keyword_embedder(vocab: List[str]) -> Callable[[str], Tuple[float, ...]]:
    """Return a deterministic, pure embedder.

    The embedder maps text to a float tuple with one component per vocab term:
    ``1.0`` if the (lowercased) term appears as a whitespace token in the
    (lowercased) text, otherwise ``0.0``.
    """
    terms = tuple((str(term).lower() for term in vocab))

    def embed(text: str) -> Tuple[float, ...]:
        tokens = set((text or '').lower().split())
        return tuple((1.0 if term in tokens else 0.0 for term in terms))
    return embed

def _cosine_distance(a: Tuple[float, ...], b: Tuple[float, ...]) -> float:
    """Cosine distance ``1 - cos_sim`` in ``[0.0, 2.0]``; 1.0 for a zero vector."""
    dot = sum((x * y for x, y in zip(a, b)))
    norm_a = math.sqrt(sum((x * x for x in a)))
    norm_b = math.sqrt(sum((y * y for y in b)))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)
_SCHEMA = '\nCREATE TABLE IF NOT EXISTS entities (\n    id TEXT PRIMARY KEY,\n    name TEXT,\n    type TEXT,\n    description TEXT,\n    attributes_json TEXT,\n    sources_json TEXT,\n    confidence REAL,\n    created_at TEXT,\n    updated_at TEXT\n);\nCREATE TABLE IF NOT EXISTS facts (\n    id TEXT PRIMARY KEY,\n    subject TEXT,\n    predicate TEXT,\n    object TEXT,\n    confidence REAL,\n    sources_json TEXT,\n    discovered_at TEXT\n);\nCREATE TABLE IF NOT EXISTS relations (\n    id TEXT PRIMARY KEY,\n    subject TEXT,\n    predicate TEXT,\n    object TEXT,\n    description TEXT,\n    weight REAL,\n    sources_json TEXT\n);\nCREATE TABLE IF NOT EXISTS tasks (\n    id TEXT PRIMARY KEY,\n    task_type TEXT,\n    status TEXT,\n    revenue_usd REAL,\n    duration_seconds REAL,\n    quality_score REAL\n);\nCREATE TABLE IF NOT EXISTS opportunities (\n    id TEXT PRIMARY KEY,\n    title TEXT,\n    description TEXT\n);\n'

class KGStore:
    """SQLite-backed knowledge store with a deterministic cosine search seam."""

    def __init__(self, sqlite_path: str, chroma_path: str, embedder: Callable[[str], Tuple[float, ...]]) -> None:
        self.sqlite_path = sqlite_path
        self.chroma_path = chroma_path
        self._embedder = embedder
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            connection = sqlite3.connect(self.sqlite_path)
            connection.row_factory = sqlite3.Row
            connection.executescript(_SCHEMA)
            connection.commit()
            self._conn = connection
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _dump(value: Any, fallback: Any) -> str:
        if value is None:
            value = fallback
        return json.dumps(value)

    @staticmethod
    def _load(raw: Optional[str], fallback: Any) -> Any:
        if raw is None:
            return fallback
        return json.loads(raw)

    def upsert_entity(self, entity: Any) -> None:
        self.conn.execute('INSERT OR REPLACE INTO entities (id, name, type, description, attributes_json, sources_json, confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (entity.id, entity.name, entity.type, getattr(entity, 'description', '') or '', self._dump(getattr(entity, 'attributes', None), {}), self._dump(getattr(entity, 'sources', None), []), getattr(entity, 'confidence', None), getattr(entity, 'created_at', None), getattr(entity, 'updated_at', None)))
        self.conn.commit()

    def _entity_row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        record = {column: row[column] for column in ENTITY_COLUMNS}
        record['attributes'] = self._load(row['attributes_json'], {})
        record['sources'] = self._load(row['sources_json'], [])
        return record

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute('SELECT * FROM entities WHERE id = ?', (entity_id,)).fetchone()
        if row is None:
            return None
        return self._entity_row_to_dict(row)

    def get_entities_by_type(self, entity_type: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute('SELECT * FROM entities WHERE type = ?', (entity_type,)).fetchall()
        return [self._entity_row_to_dict(row) for row in rows]

    def count_entities(self, entity_type: Optional[str]=None) -> int:
        if entity_type is None:
            row = self.conn.execute('SELECT COUNT(*) FROM entities').fetchone()
        else:
            row = self.conn.execute('SELECT COUNT(*) FROM entities WHERE type = ?', (entity_type,)).fetchone()
        return int(row[0])

    def upsert_fact(self, fact: Any) -> None:
        self.conn.execute('INSERT OR REPLACE INTO facts (id, subject, predicate, object, confidence, sources_json, discovered_at) VALUES (?, ?, ?, ?, ?, ?, ?)', (fact.id, fact.subject, fact.predicate, fact.object, getattr(fact, 'confidence', None), self._dump(getattr(fact, 'sources', None), []), getattr(fact, 'discovered_at', None)))
        self.conn.commit()

    @staticmethod
    def _fact_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        record = dict(row)
        record['sources'] = KGStore._load(row['sources_json'], [])
        return record

    def get_facts_about(self, term: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute('SELECT * FROM facts WHERE subject = ? OR object = ?', (term, term)).fetchall()
        return [self._fact_row_to_dict(row) for row in rows]

    def count_facts(self) -> int:
        row = self.conn.execute('SELECT COUNT(*) FROM facts').fetchone()
        return int(row[0])

    def upsert_relation(self, relation: Any) -> None:
        self.conn.execute('INSERT OR REPLACE INTO relations (id, subject, predicate, object, description, weight, sources_json) VALUES (?, ?, ?, ?, ?, ?, ?)', (relation.id, relation.subject, relation.predicate, relation.object, getattr(relation, 'description', None), getattr(relation, 'weight', None), self._dump(getattr(relation, 'sources', None), [])))
        self.conn.commit()

    @staticmethod
    def _relation_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        record = dict(row)
        record['sources'] = KGStore._load(row['sources_json'], [])
        return record

    def get_relations_for(self, term: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute('SELECT * FROM relations WHERE subject = ? OR object = ?', (term, term)).fetchall()
        return [self._relation_row_to_dict(row) for row in rows]

    def count_relations(self) -> int:
        row = self.conn.execute('SELECT COUNT(*) FROM relations').fetchone()
        return int(row[0])

    def record_task(self, task_id: str, task_type: str, status: str='pending', revenue_usd: float=0.0, duration_seconds: float=0.0, quality_score: float=0.0) -> None:
        self.conn.execute('INSERT OR REPLACE INTO tasks (id, task_type, status, revenue_usd, duration_seconds, quality_score) VALUES (?, ?, ?, ?, ?, ?)', (task_id, task_type, status, float(revenue_usd), float(duration_seconds), float(quality_score)))
        self.conn.commit()

    def get_tasks_by_status(self, status: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute('SELECT * FROM tasks WHERE status = ?', (status,)).fetchall()
        return [dict(row) for row in rows]

    def get_revenue_summary(self) -> Dict[str, Any]:
        row = self.conn.execute("SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed, SUM(revenue_usd) AS revenue, SUM(duration_seconds) AS duration, SUM(quality_score) AS quality FROM tasks").fetchone()
        total = int(row['total'] or 0)
        completed = int(row['completed'] or 0)
        total_revenue = float(row['revenue'] or 0.0)
        total_duration = float(row['duration'] or 0.0)
        total_quality = float(row['quality'] or 0.0)
        avg_duration = total_duration / total if total else 0.0
        avg_quality = total_quality / total if total else 0.0
        summary = {'total_tasks': total, 'completed': completed, 'total_revenue': total_revenue, 'avg_duration': avg_duration, 'avg_quality': avg_quality}
        return {field_name: summary[field_name] for field_name in REVENUE_SUMMARY_KEYS}

    def _search(self, query: str, n: int, rows: List[sqlite3.Row], document_for: Callable[[sqlite3.Row], str]) -> List[Dict[str, Any]]:
        if not rows:
            return []
        query_vec = self._embedder(query)
        results: List[Dict[str, Any]] = []
        for row in rows:
            document = document_for(row)
            distance = _cosine_distance(query_vec, self._embedder(document))
            results.append({'id': row['id'], 'distance': distance, 'document': document})
        results.sort(key=lambda item: (item['distance'], item['id']))
        return results[:n]

    def find_similar_entities(self, query: str, n: int=5) -> List[Dict[str, Any]]:
        rows = self.conn.execute('SELECT * FROM entities').fetchall()

        def document_for(row: sqlite3.Row) -> str:
            return '{0} {1}'.format(row['name'] or '', row['description'] or '').strip()
        return self._search(query, n, rows, document_for)

    def find_similar_facts(self, query: str, n: int=5) -> List[Dict[str, Any]]:
        rows = self.conn.execute('SELECT * FROM facts').fetchall()

        def document_for(row: sqlite3.Row) -> str:
            return '{0} {1} {2}'.format(row['subject'] or '', row['predicate'] or '', row['object'] or '').strip()
        return self._search(query, n, rows, document_for)

    def find_matching_opportunities(self, query: str, n: int=5) -> List[Dict[str, Any]]:
        rows = self.conn.execute('SELECT * FROM opportunities').fetchall()

        def document_for(row: sqlite3.Row) -> str:
            return '{0} {1}'.format(row['title'] or '', row['description'] or '').strip()
        return self._search(query, n, rows, document_for)

    def stats(self) -> Dict[str, int]:
        return {'entities': self.count_entities(), 'facts': self.count_facts(), 'relations': self.count_relations()}