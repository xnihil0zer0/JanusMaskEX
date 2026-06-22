"""RED paired oracle: pure ``targets_dir`` resolver + config reader.

Pins the resolution convention introduced by the ``targets-dir-convention-impl``
task in :mod:`harness.target_bootstrap`:

* ``_read_targets_dir(config=None)`` -- a PURE config reader that yields the
  effective targets dir (``config`` dict > ``CONFIG_DIR/target_bootstrap.yaml``
  > the ``~/NobleGreedv2/targets`` default), always absolute and ``~``-free.
* ``resolve_target_path(working_dir, config=None)`` -- a PURE resolver that maps
  a bare/relative name UNDER the targets dir (outside the repo), leaves an
  absolute path untouched, and NEVER touches the filesystem.

This file is RED today: ``resolve_target_path`` / ``_read_targets_dir`` /
``_DEFAULT_TARGETS_DIR`` do not exist yet in ``harness/target_bootstrap.py``, so
the top-level import below fails at collection time. It turns GREEN once the impl
task lands those symbols and wires line 297 of ``bootstrap_target``.

Hermetic: drives resolution purely via the passed ``config`` dict and via
``monkeypatch.setattr('harness.paths.CONFIG_DIR', <tmp>)`` (picked up by the
impl's lazy in-body ``from harness.paths import CONFIG_DIR``). It uses only
``tmp_path``/``monkeypatch``, never mutates the real ``~/NobleGreedv2/targets``,
and never invokes the mutating ``bootstrap_target`` (git/venv) body.
"""
from __future__ import annotations
from pathlib import Path
from harness.target_bootstrap import resolve_target_path, _read_targets_dir
from harness.paths import PROJECT_ROOT
_EXPECTED_DEFAULT = Path('~/NobleGreedv2/targets').expanduser().resolve()
_REAL_TARGETS = Path('~/NobleGreedv2/targets').expanduser()

def test_bare_name_resolves_under_targets_dir_via_config_outside_repo(tmp_path):
    """Req 1: a bare name nests under targets_dir, OUTSIDE the repo."""
    targets = tmp_path / 'targets_root'
    targets.mkdir()
    result = resolve_target_path('fastgpt', config={'targets_dir': str(targets)})
    assert result == (targets / 'fastgpt').resolve()
    proj = Path(PROJECT_ROOT).resolve()
    assert proj not in result.parents
    assert result != proj

def test_default_targets_dir_tilde_expansion_absolute_no_literal_tilde(tmp_path, monkeypatch):
    """Req 2: with no config and an empty CONFIG_DIR, default = expanded ~ path."""
    empty_cfg = tmp_path / 'cfg'
    empty_cfg.mkdir()
    monkeypatch.setattr('harness.paths.CONFIG_DIR', empty_cfg, raising=False)
    td = _read_targets_dir()
    assert td == _EXPECTED_DEFAULT
    assert td.is_absolute()
    assert '~' not in str(td)
    result = resolve_target_path('mem0')
    assert result == (_EXPECTED_DEFAULT / 'mem0').resolve()

def test_config_file_override_via_monkeypatched_config_dir(tmp_path, monkeypatch):
    """Req 3: CONFIG_DIR/target_bootstrap.yaml overrides the default."""
    cfg_dir = tmp_path / 'cfg'
    cfg_dir.mkdir()
    tmp2 = tmp_path / 'other_targets'
    tmp2.mkdir()
    (cfg_dir / 'target_bootstrap.yaml').write_text('targets_dir: "{}"\n'.format(tmp2), encoding='utf-8')
    monkeypatch.setattr('harness.paths.CONFIG_DIR', cfg_dir, raising=False)
    td = _read_targets_dir()
    assert td == Path(tmp2).expanduser().resolve()
    assert td.is_absolute()
    assert '~' not in str(td)

def test_absolute_external_path_returned_unchanged(tmp_path):
    """Req 4: an absolute path OUTSIDE repo+targets_dir is returned unchanged."""
    abs_path = tmp_path / 'somewhere_else'
    targets = tmp_path / 'targets_root'
    result = resolve_target_path(str(abs_path), config={'targets_dir': str(targets)})
    assert result == Path(str(abs_path)).resolve()
    assert Path(targets).resolve() not in result.parents

def test_relative_path_nests_under_targets_dir(tmp_path):
    """Req 5: a multi-segment relative path nests under targets_dir."""
    targets = tmp_path / 'targets_root'
    result = resolve_target_path('sub/dir', config={'targets_dir': str(targets)})
    assert result == (targets / 'sub' / 'dir').resolve()

def test_resolve_target_path_is_pure_no_mkdir(tmp_path):
    """Req 6: resolving a name does NOT create it on disk."""
    targets = tmp_path / 'targets_root'
    targets.mkdir()
    resolve_target_path('newname', config={'targets_dir': str(targets)})
    assert not (targets / 'newname').exists()

def test_failsafe_empty_config_falls_back_to_default(tmp_path, monkeypatch):
    """Req 7: an empty/falsey targets_dir falls back to the default, not ''."""
    empty_cfg = tmp_path / 'cfg'
    empty_cfg.mkdir()
    monkeypatch.setattr('harness.paths.CONFIG_DIR', empty_cfg, raising=False)
    td = _read_targets_dir(config={'targets_dir': ''})
    assert td == _EXPECTED_DEFAULT
    assert str(td) != ''
    assert td.is_absolute()

def test_resolver_never_mutates_filesystem_property(tmp_path):
    """Property: resolving many names never creates anything under targets_dir."""
    targets = tmp_path / 'targets_root'
    targets.mkdir()
    before = sorted((p.name for p in targets.iterdir()))
    names = ['a', 'b/c', 'deep/nested/path', 'x.y.z', 'fastgpt', 'mem0']
    for name in names:
        resolve_target_path(name, config={'targets_dir': str(targets)})
    after = sorted((p.name for p in targets.iterdir()))
    assert after == before
    for name in names:
        first_seg = name.split('/')[0]
        assert not (targets / first_seg).exists()

def test_read_targets_dir_always_absolute_and_tilde_free(tmp_path, monkeypatch):
    """Property: every config shape yields an absolute, ~-free Path."""
    empty_cfg = tmp_path / 'cfg'
    empty_cfg.mkdir()
    monkeypatch.setattr('harness.paths.CONFIG_DIR', empty_cfg, raising=False)
    valid = tmp_path / 'tdir'
    cases = [None, {}, {'targets_dir': ''}, {'targets_dir': '   '}, {'targets_dir': str(valid)}]
    for cfg in cases:
        td = _read_targets_dir(config=cfg)
        assert isinstance(td, Path)
        assert td.is_absolute()
        assert '~' not in str(td)

def test_real_targets_dir_never_touched_hermetic(tmp_path, monkeypatch):
    """Regression: default resolution never creates/mutates the real targets dir."""
    existed_before = _REAL_TARGETS.exists()
    listing_before = sorted((str(p) for p in _REAL_TARGETS.iterdir())) if existed_before else []
    empty_cfg = tmp_path / 'cfg'
    empty_cfg.mkdir()
    monkeypatch.setattr('harness.paths.CONFIG_DIR', empty_cfg, raising=False)
    assert _read_targets_dir() == _EXPECTED_DEFAULT
    resolve_target_path('ghost_target_xyz')
    assert _REAL_TARGETS.exists() == existed_before
    listing_after = sorted((str(p) for p in _REAL_TARGETS.iterdir())) if _REAL_TARGETS.exists() else []
    assert listing_after == listing_before
    assert not (_REAL_TARGETS / 'ghost_target_xyz').exists()

def test_oracle_never_invokes_bootstrap_target(tmp_path, monkeypatch):
    """Regression: the pure resolver never calls the mutating bootstrap body."""
    import harness.target_bootstrap as tb
    calls = []

    def _boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('bootstrap_target must not be invoked by the resolver')
    monkeypatch.setattr(tb, 'bootstrap_target', _boom, raising=False)
    targets = tmp_path / 'targets_root'
    targets.mkdir()
    resolve_target_path('fastgpt', config={'targets_dir': str(targets)})
    resolve_target_path('sub/dir', config={'targets_dir': str(targets)})
    _read_targets_dir(config={'targets_dir': str(targets)})
    assert calls == []