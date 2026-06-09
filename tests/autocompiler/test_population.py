"""RED oracle — authoritative contract for autocompiler/population.py (leaf ac-population-db).

Contract: ``Candidate`` is a dataclass with fields ``id`` (str), ``code`` (str),
``files`` (dict[str, str]), ``fitness`` (dict), ``elo`` (float), ``n_selected``
(int), ``parent_ids`` (list[str]). ``PopulationDB(state_dir)`` persists
candidates as JSON under the INJECTED ``state_dir`` (durable-JSON pattern of
overseer/procedure_state.py): ``add(c)``, ``get(id) -> Candidate | None``,
``candidates() -> list[Candidate]``, ``__len__``, ``save()``,
``PopulationDB.load(state_dir) -> PopulationDB`` (classmethod). Loading a
missing or corrupted store returns an EMPTY DB — never raises. Pure stdlib;
no process/model/network I/O.
"""
import json
from pathlib import Path

from autocompiler.population import Candidate, PopulationDB


def _cand(cid='c1', elo=1200.0):
    return Candidate(id=cid, code='x = 1\n', files={'autocompiler/x.py': 'x = 1\n'},
                     fitness={'score': 0.5, 'prune': False}, elo=elo, n_selected=0,
                     parent_ids=[])


def test_add_get_roundtrip(tmp_path):
    db = PopulationDB(tmp_path)
    c = _cand()
    db.add(c)
    got = db.get('c1')
    assert got is not None
    assert got.id == 'c1' and got.code == 'x = 1\n'
    assert got.files == {'autocompiler/x.py': 'x = 1\n'}
    assert got.elo == 1200.0 and got.parent_ids == []
    assert len(db) == 1


def test_save_load_roundtrip(tmp_path):
    db = PopulationDB(tmp_path)
    db.add(_cand('a', 1100.0))
    db.add(_cand('b', 1300.0))
    db.save()
    db2 = PopulationDB.load(tmp_path)
    assert len(db2) == 2
    assert db2.get('b').elo == 1300.0
    ids = {c.id for c in db2.candidates()}
    assert ids == {'a', 'b'}


def test_save_writes_json_under_state_dir(tmp_path):
    db = PopulationDB(tmp_path)
    db.add(_cand())
    db.save()
    written = list(Path(tmp_path).rglob('*.json'))
    assert written, 'save() must persist JSON under the injected state_dir'
    json.loads(written[0].read_text())


def test_get_unknown_returns_none(tmp_path):
    db = PopulationDB(tmp_path)
    assert db.get('nope') is None


def test_load_missing_dir_is_empty(tmp_path):
    db = PopulationDB.load(tmp_path / 'does' / 'not' / 'exist')
    assert len(db) == 0
    assert db.candidates() == []


def test_load_corrupted_store_is_empty_not_raise(tmp_path):
    db = PopulationDB(tmp_path)
    db.add(_cand())
    db.save()
    for p in Path(tmp_path).rglob('*.json'):
        p.write_text('{not json!!')
    db2 = PopulationDB.load(tmp_path)
    assert len(db2) == 0
