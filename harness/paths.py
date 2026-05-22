"""Canonical path constants for the JanusMask project tree.

Derived at import time from ``__file__`` so the harness is portable
across checkouts and hosts. Use these constants instead of hardcoding
``/home/xnihil0zer0/JanusMask/...`` anywhere in ``harness/*.py`` or
``harness/config.yaml``.

String variants (``*_STR``) are provided for callers that need to
interpolate into YAML/JSON or compare against ``str``-typed ledger rows.
"""
from __future__ import annotations
from pathlib import Path
HARNESS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = HARNESS_DIR.parent
CONFIG_DIR = PROJECT_ROOT / 'config'
STATE_DIR = PROJECT_ROOT / 'state'
HARNESS_DIR_STR = str(HARNESS_DIR)
PROJECT_ROOT_STR = str(PROJECT_ROOT)
CONFIG_DIR_STR = str(CONFIG_DIR)
STATE_DIR_STR = str(STATE_DIR)
__all__ = ['HARNESS_DIR', 'PROJECT_ROOT', 'CONFIG_DIR', 'STATE_DIR', 'HARNESS_DIR_STR', 'PROJECT_ROOT_STR', 'CONFIG_DIR_STR', 'STATE_DIR_STR']