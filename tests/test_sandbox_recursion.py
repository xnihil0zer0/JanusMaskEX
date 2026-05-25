import textwrap
import pytest
from hypothesis import given, settings, strategies as st
import resource
import os
import sys

from harness.sandbox import SandboxConfig, sandbox_from_config, _RUNNER_TEMPLATE, Sandbox

def test_config_defaults_recursion_and_stack():
    cfg = SandboxConfig()
    assert cfg.recursion_limit == 10000
    assert cfg.stack_mb == 64

def test_config_yaml_plumbing():
    sb = sandbox_from_config({"sandbox": {"recursion_limit": 5000, "stack_mb": 16}})
    assert sb.config.recursion_limit == 5000
    assert sb.config.stack_mb == 16

def test_runner_template_contains_setrecursionlimit():
    assert "setrecursionlimit" in _RUNNER_TEMPLATE
    assert "RLIMIT_STACK" in _RUNNER_TEMPLATE

def test_recursion_limit_clamped_to_ceiling():
    cfg = SandboxConfig(recursion_limit=10**9)
    assert cfg.recursion_limit <= 10**6

def test_deep_recursive_function_completes():
    code = textwrap.dedent("""
        def rec(n):
            if n <= 0: return 0
            return 1 + rec(n - 1)
    """)
    sb = Sandbox()
    result = sb.execute(code, "rec", args=[5000])
    assert result.success is True
    assert result.return_value == 5000

@settings(max_examples=5, deadline=None)
@given(st.integers(min_value=100, max_value=8000))
def test_recursion_depth_below_limit_always_succeeds(depth):
    code = textwrap.dedent("""
        def rec(n):
            if n <= 0: return 0
            return 1 + rec(n - 1)
    """)
    sb = Sandbox()
    result = sb.execute(code, "rec", args=[depth])
    assert result.success is True
    assert result.return_value == depth

import subprocess

def test_stack_rlimit_fallback_does_not_crash():
    code = textwrap.dedent("""
        import resource
        import textwrap
        from harness.sandbox import Sandbox, SandboxConfig
        
        soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
        small_limit = 2 * 1024 * 1024
        if hard == resource.RLIM_INFINITY or hard > small_limit:
            resource.setrlimit(resource.RLIMIT_STACK, (small_limit, small_limit))
            
        sb = Sandbox(SandboxConfig(stack_mb=64))
        run_code = textwrap.dedent('''
            def run():
                import resource
                soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
                return hard
        ''')
        result = sb.execute(run_code, "run")
        assert result.success is True
        assert "stack_rlimit_fallback" in result.stderr
        print("OK")
    """)
    
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, f"Subprocess failed: {proc.stderr}"
    assert "OK" in proc.stdout

def test_recursion_error_still_raised_at_ceiling():
    sb = Sandbox(SandboxConfig(recursion_limit=500, stack_mb=16))
    code = textwrap.dedent("""
        def rec(n):
            if n <= 0: return 0
            return 1 + rec(n - 1)
    """)
    # Exceed the limit by enough to hit RecursionError
    result = sb.execute(code, "rec", args=[1000])
    assert result.success is False
    assert result.exception_type == "RecursionError"
