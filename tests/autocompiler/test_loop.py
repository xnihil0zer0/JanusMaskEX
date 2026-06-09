"""RED oracle — authoritative contract for autocompiler/loop.py (leaf ac-loop).

Contract: pure ``step(db, seams) -> PopulationDB`` — ONE select→operate→run→
fitness→insert→rate transition over a PopulationDB (autocompiler.population).
``seams`` is a dict of INJECTED callables; step performs NO other I/O (no
subprocess, no model spawn, no network):

* ``seams['operate'](parent: Candidate) -> Candidate`` — produce a child
  candidate from the P-UCB-selected parent (selection per
  autocompiler.selection.p_ucb; the chosen parent's ``n_selected`` increments).
* ``seams['run'](child: Candidate) -> fuzz-result-like`` — duck-typed result
  (attrs ``equivalent``, ``failures``; optional ``pathology``).
* ``seams['rate'](child: Candidate, parent: Candidate) -> float`` — pairwise
  score for the child (1.0/0.5/0.0), driving an Elo update for both.

Behaviour pinned here: the child's ``fitness`` comes from
autocompiler.fitness.compute_fitness over the run result; ``parent_ids`` of
the inserted child == [parent.id]; a PRUNED child (fitness['prune'] True, e.g.
pathology='error') is NOT inserted; an EMPTY db is returned unchanged with NO
seam called.
"""
from types import SimpleNamespace

from autocompiler.population import Candidate, PopulationDB
from autocompiler.loop import step


def _seed(tmp_path, cid='seed'):
    db = PopulationDB(tmp_path)
    db.add(Candidate(id=cid, code='x = 1\n', files={'m.py': 'x = 1\n'},
                     fitness={'score': 1.0, 'prune': False}, elo=1200.0,
                     n_selected=0, parent_ids=[]))
    return db


def _child(parent):
    return Candidate(id=parent.id + '-child', code='x = 2\n', files={'m.py': 'x = 2\n'},
                     fitness={}, elo=1200.0, n_selected=0, parent_ids=[])


def test_empty_db_noop_no_seams_called(tmp_path):
    calls = []
    seams = {'operate': lambda p: calls.append('operate'),
             'run': lambda c: calls.append('run'),
             'rate': lambda c, p: calls.append('rate')}
    db = PopulationDB(tmp_path)
    out = step(db, seams)
    assert len(out) == 0
    assert calls == []


def test_step_inserts_rated_child(tmp_path):
    db = _seed(tmp_path)
    calls = {'operate': 0, 'run': 0, 'rate': 0}

    def operate(parent):
        calls['operate'] += 1
        assert parent.id == 'seed'
        return _child(parent)

    def run(child):
        calls['run'] += 1
        return SimpleNamespace(equivalent=True, failures=[], total_inputs=20)

    def rate(child, parent):
        calls['rate'] += 1
        return 1.0
    out = step(db, seams={'operate': operate, 'run': run, 'rate': rate})
    assert calls == {'operate': 1, 'run': 1, 'rate': 1}
    assert len(out) == 2
    child = out.get('seed-child')
    assert child is not None
    assert child.parent_ids == ['seed']
    assert child.fitness.get('prune') is False
    assert child.fitness.get('score') == 1.0
    assert out.get('seed').n_selected == 1
    assert child.elo > out.get('seed').elo, 'winning child must gain Elo over the parent'


def test_pruned_child_not_inserted(tmp_path):
    db = _seed(tmp_path)

    def run(child):
        return SimpleNamespace(equivalent=False, failures=[1, 2, 3], total_inputs=20,
                               pathology='error')
    out = step(db, seams={'operate': _child, 'run': run, 'rate': lambda c, p: 0.0})
    assert len(out) == 1, 'a prune-floored child must be kept OUT of the population'
    assert out.get('seed-child') is None


def test_near_miss_child_is_kept(tmp_path):
    db = _seed(tmp_path)

    def run(child):
        return SimpleNamespace(equivalent=False, failures=[1], total_inputs=20)
    out = step(db, seams={'operate': _child, 'run': run, 'rate': lambda c, p: 0.0})
    assert len(out) == 2, 'a near-miss is RATED and retained, not discarded'
    kept = out.get('seed-child')
    assert 0.0 < kept.fitness['score'] < 1.0
