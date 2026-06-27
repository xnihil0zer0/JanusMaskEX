"""RED oracle: ``harness.planner.brief_loader.load_brief`` must parse a
frontmatter ``integration_contracts`` mapping (``task_id -> {entrypoints,
symbols, runtime_oracle}``) into a new ``PlanningBrief.integration_contracts``
dict, and default that field to ``{}`` when the key is absent (an opt-in,
no-behaviour-change default).

This is an EFFECT-OBSERVING unit oracle: every case writes a real fixture brief
``.md`` ON DISK under the pytest ``tmp_path`` fixture and then calls the REAL
``brief_loader.load_brief(path)`` -- nothing about ``load_brief`` is mocked or
stubbed, so the assertions exercise the loader's genuine observable behaviour.

It is RED on current HEAD because ``PlanningBrief`` has no
``integration_contracts`` attribute and ``load_brief`` never parses the key, so
every assertion that touches ``brief.integration_contracts`` raises
``AttributeError`` today; the file turns GREEN once that parse lands.

NON-GOALS: this is a pure unit test of brief_loader parsing -- a dedicated live
integration wire-up test is out of scope and not meaningful here, so the
integration-test requirement is excused (this module, and its fixture
Non-Goals body, deliberately carry the literal word integration). It asserts
nothing about the normalizer or the cli (those are separate red-pairs), and it
edits no production code.

All declared/expected contract values are TEST-LOCAL python literals built
inside each test, never read from any implementation_notes or shared blob, so
the assertions are independent of the production source.

NESTED-QUOTE HAZARD: this module uses only triple-double-quote docstrings.
"""
from harness.planner import brief_loader
WORKING_DIR = '/home/xnihil0zer0/AI-Data/JanusMaskEX'
BODY_SECTIONS = '# Title\nWireup contract brief-loader oracle fixture.\n\n# Scope\nExercise the real load_brief frontmatter parse path on disk.\n\n# Non-Goals\nNo live integration wire-up gate is exercised here; parsing only.\n\n# Inputs\nA single fixture brief written under tmp_path.\n\n# Deliverables\nA parsed PlanningBrief object.\n'

def _write_brief(tmp_path, frontmatter, name='brief.md'):
    """Write a complete, valid brief ``.md`` under ``tmp_path``; return its path.

    ``frontmatter`` is the YAML frontmatter body WITHOUT the ``---`` fences.
    Pass ``None`` to emit a brief that has no frontmatter block at all.
    """
    if frontmatter is None:
        content = BODY_SECTIONS
    else:
        content = '---\n' + frontmatter.strip('\n') + '\n---\n\n' + BODY_SECTIONS
    path = tmp_path / name
    path.write_text(content, encoding='utf-8')
    return path

def _contract_frontmatter(task_id, entrypoints, symbols, runtime_oracle, required_task_ids=()):
    """Build YAML frontmatter declaring an ``integration_contracts`` entry for
    ``task_id`` from the given TEST-LOCAL literals (mirrors the existing
    required_task_ids YAML block-list style)."""
    lines = ['working_dir: ' + WORKING_DIR]
    if required_task_ids:
        lines.append('required_task_ids:')
        for rid in required_task_ids:
            lines.append('  - "' + rid + '"')
    lines.append('integration_contracts:')
    lines.append('  ' + task_id + ':')
    lines.append('    entrypoints:')
    for entry in entrypoints:
        lines.append('      - "' + entry + '"')
    lines.append('    symbols:')
    for sym in symbols:
        lines.append('      - "' + sym + '"')
    lines.append('    runtime_oracle: "' + runtime_oracle + '"')
    return '\n'.join(lines)

def test_load_brief_parses_integration_contracts_verbatim(tmp_path):
    task_id = 't1'
    entrypoints = ['harness/orchestrator.py']
    symbols = ['foo_handler']
    runtime_oracle = 'calls foo_handler from orchestrator iter'
    frontmatter = _contract_frontmatter(task_id, entrypoints, symbols, runtime_oracle, required_task_ids=['task-a', 'task-b'])
    path = _write_brief(tmp_path, frontmatter)
    brief = brief_loader.load_brief(path)
    assert isinstance(brief.integration_contracts, dict)
    assert task_id in brief.integration_contracts
    assert task_id not in brief.required_task_ids
    contract = brief.integration_contracts[task_id]
    assert contract['entrypoints'] == ['harness/orchestrator.py']
    assert contract['symbols'] == ['foo_handler']
    assert contract['runtime_oracle'] == 'calls foo_handler from orchestrator iter'

def test_load_brief_no_contracts_yields_empty_dict(tmp_path):
    frontmatter = 'working_dir: ' + WORKING_DIR
    path = _write_brief(tmp_path, frontmatter)
    brief = brief_loader.load_brief(path)
    assert brief.integration_contracts == {}
    assert brief.integration_contracts is not None
    assert isinstance(brief.integration_contracts, dict)

def test_declared_values_are_test_local_literals(tmp_path):
    task_id = 'wire-2'
    expected = {task_id: {'entrypoints': ['harness/normalizer.py', 'harness/cli.py'], 'symbols': ['bar_handler'], 'runtime_oracle': 'invokes bar_handler during normalize pass'}}
    contract = expected[task_id]
    frontmatter = _contract_frontmatter(task_id, contract['entrypoints'], contract['symbols'], contract['runtime_oracle'])
    path = _write_brief(tmp_path, frontmatter)
    brief = brief_loader.load_brief(path)
    assert brief.integration_contracts == expected

def test_contract_entry_keys_restricted_to_entrypoints_symbols_runtime_oracle(tmp_path):
    task_id = 't1'
    frontmatter = _contract_frontmatter(task_id, entrypoints=['harness/orchestrator.py'], symbols=['foo_handler'], runtime_oracle='calls foo_handler from orchestrator iter')
    path = _write_brief(tmp_path, frontmatter)
    brief = brief_loader.load_brief(path)
    entry = brief.integration_contracts[task_id]
    assert set(entry.keys()) == {'entrypoints', 'symbols', 'runtime_oracle'}

def test_existing_required_task_ids_parse_unaffected(tmp_path):
    task_id = 't1'
    frontmatter = _contract_frontmatter(task_id, entrypoints=['harness/orchestrator.py'], symbols=['foo_handler'], runtime_oracle='calls foo_handler from orchestrator iter', required_task_ids=['alpha', 'beta'])
    path = _write_brief(tmp_path, frontmatter)
    brief = brief_loader.load_brief(path)
    assert brief.required_task_ids == ('alpha', 'beta')
    assert brief.integration_contracts[task_id]['symbols'] == ['foo_handler']

def test_brief_with_no_frontmatter_extra_keys_still_loads(tmp_path):
    frontmatter = 'working_dir: ' + WORKING_DIR
    path = _write_brief(tmp_path, frontmatter)
    brief = brief_loader.load_brief(path)
    assert brief.title == 'Wireup contract brief-loader oracle fixture.'
    assert brief.required_task_ids == ()
    assert brief.integration_contracts == {}