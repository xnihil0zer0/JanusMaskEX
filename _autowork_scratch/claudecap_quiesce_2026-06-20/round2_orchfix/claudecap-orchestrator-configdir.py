__JANUSMASK_PATCHES__ = [
    {
        'file': 'harness/orchestrator.py',
        'kind': 'symbol',
        'name': '_apply_agy_pool_env',
        'code': r'''def _seed_claude_config_dir(work_dir):
    from pathlib import Path
    config_dir = Path(work_dir) / '.claude'
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return {'CLAUDE_CONFIG_DIR': str(config_dir)}

def _apply_agy_pool_env(agent, env, config=None):
    """Pool a private $HOME onto an agy agent's spawn env when the worker pool
    is enabled and this worker was assigned a slot (JANUSMASK_AGY_SLOT). Only
    agy-command agents are pooled; disabled / non-agy / absent or invalid slot
    returns env unchanged (never mutated). The overseer never reaches this path."""
    if config is None:
        config = load_config()
    try:
        cmd = config['agents'][agent]['command']
    except (KeyError, TypeError):
        return env
    if os.path.basename(cmd) != 'agy':
        return env
    pool = (config.get('workers') or {}).get('agy_pool') or {}
    if not pool.get('enabled'):
        return env
    try:
        slot = int(os.environ.get('JANUSMASK_AGY_SLOT'))
    except (TypeError, ValueError):
        return env
    from harness import agy_pool
    home = os.environ.get('HOME') or os.path.expanduser('~')  # home-free: allow
    try:
        agy_pool.ensure_seeded(str(PROJECT_DIR), slot, home=home, copy=shutil.copy2, exists=os.path.exists, makedirs=lambda d: os.makedirs(d, exist_ok=True))
    except OSError:
        pass
    return agy_pool.worker_env(str(PROJECT_DIR), slot, env)
'''
    },
    {
        'file': 'harness/orchestrator.py',
        'kind': 'symbol',
        'name': '_build_agent_env',
        'code': r'''def _build_agent_env(agent: str, state_dir: str, round_number: int=1) -> dict[str, str]:
    """Build the environment for an agent process.

    Every ``JANUSMASK_*`` key the worker-side hooks read is set explicitly
    so that an upstream caller that wipes one of these variables does not
    silently downgrade the worker to an un-gated fallback. See sub-plan 04
    §3.11 and the HOOK-30 authoritative-settings contract at
    ``harness/hooks/gemini/session_start.py:80-92``.

    Post-migration: we also pin ``JANUSMASK_WORK_DIR`` to a deterministic,
    per-spawn path so the Write-based submission flow has a stable outbox
    to target. The worker configs interpolate ``${SESSION_ID}`` by default
    but that id is only known at Claude CLI startup — by pre-setting
    ``JANUSMASK_WORK_DIR`` here we override the template and the outbox
    path is known to both the agent prompt and the PostToolUse hook at
    spawn time.

    Filesystem side-effects: env-building is pure — the outbox directory
    is created by ``spawn_agent`` at actual spawn time so callers can
    build env against arbitrary ``state_dir`` paths (e.g. tmp_path,
    non-existent, read-only) without tripping mkdir permission errors.
    """
    mode = os.environ.get('JANUSMASK_MODE', 'synthesis')
    task_id = os.environ.get('JANUSMASK_TASK_ID', '')
    import uuid as _uuid
    if _pin_task_cwd_enabled():
        session_slug = _pinned_session_slug(agent, round_number, task_id)
    else:
        session_slug = f'{agent}-r{round_number}-{task_id or 'notask'}-{_uuid.uuid4().hex[:8]}'
    work_dir = agent_work_dir(agent, session_slug)
    _existing_pp = os.environ.get('PYTHONPATH', '')
    _pythonpath = str(PROJECT_DIR) if not _existing_pp else str(PROJECT_DIR) + os.pathsep + _existing_pp
    _ENV_ALLOW_EXACT = frozenset(('PATH', 'HOME', 'LANG', 'LANGUAGE', 'LC_ALL', 'TERM', 'SHELL', 'USER', 'LOGNAME', 'TZ', 'TMPDIR', 'PWD', 'DBUS_SESSION_BUS_ADDRESS', 'GOOGLE_GENAI_USE_GCA', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS', 'CURL_CA_BUNDLE', 'NO_PROXY', 'no_proxy', 'HTTP_PROXY', 'http_proxy', 'HTTPS_PROXY', 'https_proxy'))
    _ENV_ALLOW_PREFIXES = ('JANUSMASK_', 'XDG_', 'NVM_', 'NODE_', 'GEMINI_', 'GOOGLE_', 'ANTHROPIC_', 'CLAUDE_', 'LC_')
    base_env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOW_EXACT or any((k.startswith(p) for p in _ENV_ALLOW_PREFIXES))}
    env: dict[str, str] = {**base_env, 'PYTHONHASHSEED': '0', 'CLAUDE_PROJECT_DIR': str(work_dir), 'JANUSMASK_PROJECT_DIR': str(PROJECT_DIR), 'PYTHONPATH': _pythonpath, 'GEMINI_CLI_TRUST_WORKSPACE': 'true', 'JANUSMASK_AGENT': agent, 'JANUSMASK_STATE_DIR': state_dir, 'JANUSMASK_ROUND': str(round_number), 'JANUSMASK_MODE': mode, 'JANUSMASK_TASK_ID': task_id, 'JANUSMASK_WORK_DIR': str(work_dir)}
    if agent == 'gemini':
        env['JANUSMASK_GEMINI_SETTINGS'] = os.environ.get('JANUSMASK_GEMINI_SETTINGS', str(PROJECT_DIR / 'config' / 'gemini_settings.json'))
    if agent == 'claude':
        claude_env = _seed_claude_config_dir(work_dir)
        if isinstance(claude_env, dict):
            env.update(claude_env)
    env = _apply_agy_pool_env(agent, env)
    return env
'''
    }
]
