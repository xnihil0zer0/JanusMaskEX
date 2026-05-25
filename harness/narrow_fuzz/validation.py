"""Narrow-fuzz module for ``meta_task_type="validation"`` (W77b.2).

Discovers candidate validator-like functions in the canary source —
top-level ``def`` matching ``^(validate_|check_|is_)`` — extracts each
function's annotated signature via
:func:`harness.diff_fuzzer.extract_function_signature`, maps Python
type-annotation strings to Hypothesis strategies per the brief §10.2
table, and runs 200 inputs per validator. Returns ``None`` on
pass/skip; on crash, returns an error string that includes the
exception type **and** the shrunken failing input (binding §13).

Per §11.2 reversed default: when the candidate source already defines
embedded ``test_*`` functions (detected via
:func:`harness.embedded_test_runner.should_run_embedded_tests`),
narrow-fuzz returns ``None`` to avoid redundant coverage. The
``RUN_NARROW_FUZZ_ALWAYS=1`` env var, read at module load, overrides
this skip.

Per §10.3 decorator opt-out: validators may carry an
``_narrow_fuzz_meta`` sentinel attribute (``{"skip": True}`` to skip,
``{"timeout": 10.0}`` to override timeout). Discovery uses ``getattr``
with a default of ``{}`` so undecorated validators run with defaults.
"""
from __future__ import annotations
import ast
import os
import re
import traceback
from typing import Any, Callable
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from harness.diff_fuzzer import extract_function_signature
from harness.embedded_test_runner import should_run_embedded_tests
_VALIDATOR_PREFIX_RE = re.compile('^(validate_|check_|is_)')
_DEFAULT_INPUT_BUDGET = 200
_RUN_ALWAYS: bool = os.environ.get('RUN_NARROW_FUZZ_ALWAYS') == '1'

def _strategy_for_annotation(annotation: str) -> st.SearchStrategy[Any] | None:
    raise NotImplementedError

def _discover_validators(module_src: str) -> list[str]:
    raise NotImplementedError

def _build_strategies(sig: dict[str, str]) -> dict[str, st.SearchStrategy[Any]] | None:
    raise NotImplementedError

def _exec_module(module_name: str, module_src: str) -> dict[str, Any] | None:
    raise NotImplementedError

def _meta_for(fn: Callable[..., Any]) -> dict[str, Any]:
    raise NotImplementedError

def _fuzz_one(fn: Callable[..., Any], name: str, strategies: dict[str, st.SearchStrategy[Any]], timeout: float) -> str | None:
    raise NotImplementedError

def fuzz(module_name: str, module_src: str, *, timeout: float=5.0) -> str | None:
    """Narrow-fuzz the candidate's validator-like functions.

    See module docstring for design contract; brief §4.1, §11.2, §13
    are the binding spec.
    """
    raise NotImplementedError