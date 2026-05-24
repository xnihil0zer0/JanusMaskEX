def _divider(agent_id: str, char: str='─', width: int=60) -> str:
    return _agent_color(agent_id) + (char * width) + '\x1b[0m'
