import yaml
from pathlib import Path

def test_ghei_loop_gate():
    config_path = Path('harness/config.yaml')
    assert config_path.is_file()
    with open(config_path) as f:
        data = yaml.safe_load(f)
    val = None
    if 'autowork' in data and 'ghei_loop_enabled' in data['autowork']:
        val = data['autowork']['ghei_loop_enabled']
    elif 'ghei_loop_enabled' in data:
        val = data['ghei_loop_enabled']
    assert val is True