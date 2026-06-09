"""RED oracle — authoritative contract for autocompiler/crossover.py (leaf ac-crossover).

Contract: ``ast_crossover(code_a, code_b, merge_seam) -> str`` delegates the
merge to the INJECTED ``merge_seam(code_a, code_b) -> str`` (production wires
harness.git_integration._ast_merge here; the oracle injects a fake — NO real
git, NO direct _ast_merge import on the call path). Fail-safe: if the seam
raises, or returns something that is not valid Python source, return
``code_a`` unchanged. ``file_crossover(files_a, files_b, fitness_a, fitness_b)
-> dict[str, str]`` composes a child file-map: files present on only one side
are kept; for files present on BOTH sides the version from the higher-
``score`` parent wins (``fitness`` dicts with a float ``score`` key; tie =>
side A). Pure and deterministic.
"""
from autocompiler.crossover import ast_crossover, file_crossover


def test_ast_crossover_delegates_to_injected_seam():
    calls = []

    def seam(a, b):
        calls.append((a, b))
        return a + b
    out = ast_crossover('x = 1\n', 'y = 2\n', seam)
    assert calls == [('x = 1\n', 'y = 2\n')], 'merge_seam must be called exactly once with (a, b)'
    assert out == 'x = 1\ny = 2\n'


def test_ast_crossover_seam_raise_falls_back_to_a():
    def seam(a, b):
        raise RuntimeError('merge exploded')
    assert ast_crossover('x = 1\n', 'y = 2\n', seam) == 'x = 1\n'


def test_ast_crossover_invalid_merge_falls_back_to_a():
    out = ast_crossover('x = 1\n', 'y = 2\n', lambda a, b: 'def broken(:\n')
    assert out == 'x = 1\n'


def test_file_crossover_disjoint_union():
    child = file_crossover({'a.py': 'A'}, {'b.py': 'B'}, {'score': 0.5}, {'score': 0.5})
    assert child == {'a.py': 'A', 'b.py': 'B'}


def test_file_crossover_common_file_higher_score_wins():
    child = file_crossover({'m.py': 'from-a'}, {'m.py': 'from-b'},
                           {'score': 0.2}, {'score': 0.9})
    assert child['m.py'] == 'from-b'


def test_file_crossover_tie_prefers_a_and_is_deterministic():
    args = ({'m.py': 'from-a'}, {'m.py': 'from-b'}, {'score': 0.5}, {'score': 0.5})
    assert file_crossover(*args)['m.py'] == 'from-a'
    assert file_crossover(*args) == file_crossover(*args)
