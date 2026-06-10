"""Execution sandbox for JanusMask differential fuzzing.

Runs code samples in isolated subprocesses with resource limits:
- Memory cap (default 256 MB)
- CPU time cap (default 10 seconds)
- No network access
- Filesystem restricted to a per-session temp directory
- Fixed PYTHONHASHSEED for determinism
"""

from __future__ import annotations

import json
import os

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import queue
import struct
import time
from typing import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

class SandboxEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, bytes):
            return {"__type__": "bytes", "data": list(obj)}
        if isinstance(obj, set):
            return {"__type__": "set", "data": list(obj)}
        import ast as _ast
        if isinstance(obj, _ast.AST):
            cat = "mod" if isinstance(obj, _ast.Module) else "expr" if isinstance(obj, _ast.expr) else "stmt"
            return {"__type__": "ast", "src": _ast.unparse(obj), "cat": cat}
        import pathlib as _pl
        if isinstance(obj, _pl.PurePath):
            return {"__type__": "path", "s": str(obj)}
        return super().default(obj)

def sandbox_decoder(dct):
    if "__type__" in dct:
        t = dct["__type__"]
        if t == "bytes":
            return bytes(dct["data"])
        if t == "set":
            return set(dct["data"])
        if t == "ast":
            import ast as _ast
            src, cat = dct["src"], dct.get("cat", "stmt")
            if cat == "mod":
                return _ast.parse(src)
            if cat == "expr":
                return _ast.parse(src, mode="eval").body
            return _ast.parse(src).body[0]
        if t == "path":
            import pathlib as _pl
            return _pl.Path(dct["s"])
    return dct


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Result of executing a code sample on a single input."""
    success: bool
    return_value: Any = None
    return_repr: str = ""
    exception_type: str | None = None
    exception_message: str | None = None
    timed_out: bool = False
    stderr: str = ""
    wall_time_ms: float = 0.0


@dataclass
class BatchResult:
    """Result of executing a batch of inputs."""
    results: list[ExecutionResult]
    total_inputs: int
    completed_inputs: int
    batch_error: str | None = None


@dataclass
class SandboxConfig:
    """Configuration for the execution sandbox."""
    memory_limit_mb: int = 256
    cpu_time_limit_seconds: int = 10
    timeout_per_input_ms: int = 5000
    filesystem_root: str = "/tmp/janusmask_sandbox"
    python_hash_seed: str = "0"
    recursion_limit: int = 10000
    stack_mb: int = 64
    seccomp: bool = True
    rlimit_nproc: int | None = None

    def __post_init__(self):
        if self.recursion_limit > 10**6:
            self.recursion_limit = 10**6



_DETERMINISM_SITE_DIRNAME = 'janusmask_det_site'

def _maybe_determinism_env(env: dict) -> dict:
    try:
        from autocompiler.flags import ac_enabled
        if not ac_enabled('determinism'):
            return env
        import tempfile
        from autocompiler.determinism import write_sitecustomize
        site_dir = os.path.join(tempfile.gettempdir(), _DETERMINISM_SITE_DIRNAME)
        write_sitecustomize(site_dir)
        existing = env.get('PYTHONPATH')
        env['PYTHONPATH'] = site_dir + os.pathsep + existing if existing else site_dir
    except Exception:
        return env
    return env
def sandbox_child_env(extra: dict | None = None) -> dict:
    """Return a fresh environment mapping with thread guards applied."""
    env = os.environ.copy()
    if extra:
        env.update(extra)
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    # gap#2b: the differential fuzzer runs candidates in a plain subprocess with
    # this env. For an EXTERNAL-target build the candidate may import packages
    # rooted at the external working_dir (e.g. `from ngv2.contracts import ...`),
    # not on the JM PYTHONPATH. Prepend that root so those imports resolve; a
    # self build (env unset / self) is inert. Mirrors the smoke-gate fix.
    try:
        _wd = env.get('JANUSMASK_WORKING_DIR')
        if _wd:
            from harness.paths import _target_is_self
            if not _target_is_self(_wd):
                _existing = env.get('PYTHONPATH')
                env['PYTHONPATH'] = str(_wd) + os.pathsep + _existing if _existing else str(_wd)
    except Exception:
        pass
    return _maybe_determinism_env(env)


# ---------------------------------------------------------------------------
# Runner script template
# ---------------------------------------------------------------------------

# This script is written to a temp file and executed in a subprocess.
# It receives the code sample and input via a JSON file, executes the
# target function with the input, and writes the result to another JSON file.
_RUNNER_TEMPLATE = textwrap.dedent("""\
    import inspect
    import json
    import os
    import resource
    import sys
    import time
    import traceback

    class SandboxEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, bytes):
                return {"__type__": "bytes", "data": list(obj)}
            if isinstance(obj, set):
                return {"__type__": "set", "data": list(obj)}
            import ast as _ast
            if isinstance(obj, _ast.AST):
                cat = "mod" if isinstance(obj, _ast.Module) else "expr" if isinstance(obj, _ast.expr) else "stmt"
                return {"__type__": "ast", "src": _ast.unparse(obj), "cat": cat}
            import pathlib as _pl
            if isinstance(obj, _pl.PurePath):
                return {"__type__": "path", "s": str(obj)}
            return super().default(obj)

    def sandbox_decoder(dct):
        if "__type__" in dct:
            t = dct["__type__"]
            if t == "bytes":
                return bytes(dct["data"])
            if t == "set":
                return set(dct["data"])
            if t == "ast":
                import ast as _ast
                src, cat = dct["src"], dct.get("cat", "stmt")
                if cat == "mod":
                    return _ast.parse(src)
                if cat == "expr":
                    return _ast.parse(src, mode="eval").body
                return _ast.parse(src).body[0]
            if t == "path":
                import pathlib as _pl
                return _pl.Path(dct["s"])
        return dct

    def _set_limits(mem_mb, cpu_sec, stack_mb):
        mem_bytes = mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec))
        
        stack_bytes = stack_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_STACK, (stack_bytes, stack_bytes))
        except ValueError:
            _, hard = resource.getrlimit(resource.RLIMIT_STACK)
            sys.stderr.write(f"stack_rlimit_fallback={hard}\\n")
            sys.stderr.flush()
            try:
                resource.setrlimit(resource.RLIMIT_STACK, (hard, hard))
            except ValueError:
                pass

    def main_single():
        payload_path = sys.argv[1]
        result_path = sys.argv[2]

        with open(payload_path, "r") as f:
            payload = json.load(f, object_hook=sandbox_decoder)

        sys.setrecursionlimit(payload.get("recursion_limit", 10000))

        code = payload["code"]
        func_name = payload["func_name"]
        call_args = payload.get("args", [])
        call_kwargs = payload.get("kwargs", {})
        mem_mb = payload.get("memory_limit_mb", 256)
        cpu_sec = payload.get("cpu_time_limit_seconds", 10)
        stack_mb = payload.get("stack_mb", 64)

        _set_limits(mem_mb, cpu_sec, stack_mb)

        namespace = {}
        try:
            exec(compile(code, "<submission>", "exec"), namespace)
        except Exception as exc:
            result = {
                "success": False,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            }
            with open(result_path, "w") as f:
                json.dump(result, f)
            return

        func = namespace.get(func_name)
        if func is None:
            result = {
                "success": False,
                "exception_type": "NameError",
                "exception_message": f"Function '{func_name}' not found in submission",
            }
            with open(result_path, "w") as f:
                json.dump(result, f)
            return

        if inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func):
            # Async functions return an unawaited coroutine when invoked
            # synchronously — repr() succeeds, json.dumps() drops it to None,
            # and a differential-fuzz pair would falsely compare equal. Reject
            # at the gate with a TypeError.
            result = {
                "success": False,
                "exception_type": "TypeError",
                "exception_message": f"async function '{func_name}' not supported in differential fuzz sandbox",
            }
            with open(result_path, "w") as f:
                json.dump(result, f)
            return

        start = time.monotonic()
        try:
            ret = func(*call_args, **call_kwargs)
            elapsed_ms = (time.monotonic() - start) * 1000
            result = {
                "success": True,
                "return_repr": repr(ret),
                "wall_time_ms": elapsed_ms,
            }
            # Try to JSON-serialize the return value for structured comparison.
            try:
                json.dumps(ret)
                result["return_value"] = ret
            except (TypeError, ValueError, OverflowError):
                result["return_value"] = None
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            result = {
                "success": False,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "wall_time_ms": elapsed_ms,
            }

        with open(result_path, "w") as f:
            json.dump(result, f)


    def main_pool():
        import signal
        import struct
        
        while True:
            try:
                length_bytes = sys.stdin.buffer.read(4)
            except Exception:
                break
            if not length_bytes:
                break
            if len(length_bytes) < 4:
                sys.exit(1)
            
            payload_len = struct.unpack(">I", length_bytes)[0]
            payload_bytes = sys.stdin.buffer.read(payload_len)
            if len(payload_bytes) < payload_len:
                sys.exit(1)
                
            payload = json.loads(payload_bytes.decode('utf-8'))
            
            inputs = payload.get("inputs", [])
            if not inputs:
                batch_done_msg = b'{"status": "batch_done"}'
                sys.stdout.buffer.write(struct.pack(">I", len(batch_done_msg)))
                sys.stdout.buffer.write(batch_done_msg)
                sys.stdout.buffer.flush()
                continue
                
            code = payload.get("code", "")
            func_name = payload.get("func_name", "")
            wall_timeout_per_input_sec = payload.get("wall_timeout_per_input_sec", 5.0)

            namespace = {}
            compile_err = None
            try:
                exec(compile(code, "<submission>", "exec"), namespace)
            except Exception as exc:
                compile_err = exc
                
            func = namespace.get(func_name)
            if compile_err is None and func is None:
                compile_err = NameError(f"Function '{func_name}' not found in submission")
            if compile_err is None and (inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func)):
                # Same silent-pass guard as main_single: refuse async submissions
                # so a differential-fuzz pair cannot falsely match on None.
                compile_err = TypeError(f"async function '{func_name}' not supported in differential fuzz sandbox")

            if compile_err is not None:
                for i in range(len(inputs)):
                    err_record = {
                        "index": i,
                        "success": False,
                        "exception_type": type(compile_err).__name__,
                        "exception_message": str(compile_err),
                        "wall_time_ms": 0.0
                    }
                    record_bytes = json.dumps(err_record, ensure_ascii=False).encode('utf-8')
                    sys.stdout.buffer.write(struct.pack(">I", len(record_bytes)))
                    sys.stdout.buffer.write(record_bytes)
                    sys.stdout.buffer.flush()
                
                batch_done_msg = b'{"status": "batch_done"}'
                sys.stdout.buffer.write(struct.pack(">I", len(batch_done_msg)))
                sys.stdout.buffer.write(batch_done_msg)
                sys.stdout.buffer.flush()
                continue
                
            try:
                for i, inp in enumerate(inputs):
                    call_args = inp.get("args", [])
                    call_kwargs = inp.get("kwargs", {})
                    
                    pipe_r, pipe_w = os.pipe()
                    pid = os.fork()
                    
                    if pid == 0:
                        os.close(pipe_r)
                        _set_child_limits(payload)
                        if payload.get("seccomp", True):
                            _install_seccomp()
                        
                        start = time.monotonic()
                        try:
                            ret = func(*call_args, **call_kwargs)
                            elapsed_ms = (time.monotonic() - start) * 1000
                            result = {
                                "index": i,
                                "success": True,
                                "return_repr": repr(ret),
                                "wall_time_ms": elapsed_ms,
                            }
                            try:
                                json.dumps(ret)
                                result["return_value"] = ret
                            except (TypeError, ValueError, OverflowError):
                                result["return_value"] = None
                        except Exception as exc:
                            elapsed_ms = (time.monotonic() - start) * 1000
                            result = {
                                "index": i,
                                "success": False,
                                "exception_type": type(exc).__name__,
                                "exception_message": str(exc),
                                "wall_time_ms": elapsed_ms,
                            }
                        
                        with os.fdopen(pipe_w, 'w') as f:
                            json.dump(result, f, ensure_ascii=False)
                            f.flush()
                        
                        os._exit(0)
                    else:
                        os.close(pipe_w)
                        os.set_blocking(pipe_r, False)
                        
                        deadline = time.monotonic() + wall_timeout_per_input_sec
                        timed_out = False
                        wpid = 0
                        status = 0
                        pipe_data = b""
                        
                        while True:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                timed_out = True
                                break
                                
                            try:
                                chunk = os.read(pipe_r, 65536)
                                if chunk:
                                    pipe_data += chunk
                            except BlockingIOError:
                                pass
                                
                            wpid, status = os.waitpid(pid, os.WNOHANG)
                            if wpid != 0:
                                try:
                                    while True:
                                        chunk = os.read(pipe_r, 65536)
                                        if not chunk:
                                            break
                                        pipe_data += chunk
                                except BlockingIOError:
                                    pass
                                break
                            time.sleep(0.005)
                            
                        if timed_out:
                            try:
                                os.kill(pid, signal.SIGKILL)
                            except OSError:
                                pass
                            os.waitpid(pid, 0)
                            os.close(pipe_r)
                            err_record = {
                                "index": i,
                                "success": False,
                                "timed_out": True,
                                "exception_type": "TimeoutError",
                                "exception_message": f"Execution timed out after {wall_timeout_per_input_sec}s",
                                "wall_time_ms": wall_timeout_per_input_sec * 1000.0
                            }
                            record_bytes = json.dumps(err_record, ensure_ascii=False).encode('utf-8')
                            sys.stdout.buffer.write(struct.pack(">I", len(record_bytes)))
                            sys.stdout.buffer.write(record_bytes)
                            sys.stdout.buffer.flush()
                            continue
                            
                        try:
                            os.close(pipe_r)
                        except OSError:
                            pass
                            
                        is_valid_json = False
                        decoded_str = ""
                        if pipe_data.strip():
                            try:
                                decoded_str = pipe_data.decode('utf-8')
                                json.loads(decoded_str)
                                is_valid_json = True
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                pass
                                
                        if is_valid_json:
                            record_bytes = decoded_str.strip().encode('utf-8')
                            sys.stdout.buffer.write(struct.pack(">I", len(record_bytes)))
                            sys.stdout.buffer.write(record_bytes)
                            sys.stdout.buffer.flush()
                            continue
                            
                        if os.WIFSIGNALED(status):
                            sig = os.WTERMSIG(status)
                            if sig in (signal.SIGKILL, signal.SIGXCPU):
                                err_record = {
                                    "index": i,
                                    "success": False,
                                    "timed_out": True,
                                    "exception_type": "TimeoutError",
                                    "exception_message": f"Child killed by signal {sig} (SIGXCPU/SIGKILL)",
                                    "wall_time_ms": 0.0
                                }
                            else:
                                err_record = {
                                    "index": i,
                                    "success": False,
                                    "exception_type": "SandboxError",
                                    "exception_message": f"Child killed: {sig}",
                                    "wall_time_ms": 0.0
                                }
                        else:
                            if not pipe_data.strip():
                                err_record = {
                                    "index": i,
                                    "success": False,
                                    "exception_type": "SandboxError",
                                    "exception_message": "Child exited without writing result",
                                    "wall_time_ms": 0.0
                                }
                            else:
                                err_record = {
                                    "index": i,
                                    "success": False,
                                    "exception_type": "SandboxError",
                                    "exception_message": "Corrupt result from child",
                                    "wall_time_ms": 0.0
                                }
                                
                        record_bytes = json.dumps(err_record, ensure_ascii=False).encode('utf-8')
                        sys.stdout.buffer.write(struct.pack(">I", len(record_bytes)))
                        sys.stdout.buffer.write(record_bytes)
                        sys.stdout.buffer.flush()
            finally:
                while True:
                    try:
                        wpid, _ = os.waitpid(-1, os.WNOHANG)
                        if wpid <= 0:
                            break
                    except ChildProcessError:
                        break
                    except OSError:
                        break

            batch_done_msg = b'{"status": "batch_done"}'
            sys.stdout.buffer.write(struct.pack(">I", len(batch_done_msg)))
            sys.stdout.buffer.write(batch_done_msg)
            sys.stdout.buffer.flush()


    if __name__ == "__main__":
        if len(sys.argv) > 1 and sys.argv[1] == "--pool":
            main_pool()
        else:
            main_single()

""")

_BATCH_RUNNER_TEMPLATE = textwrap.dedent("""\
    import inspect
    import json
    import os
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    import resource
    import sys
    import time
    import traceback

    class SandboxEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, bytes):
                return {"__type__": "bytes", "data": list(obj)}
            if isinstance(obj, set):
                return {"__type__": "set", "data": list(obj)}
            import ast as _ast
            if isinstance(obj, _ast.AST):
                cat = "mod" if isinstance(obj, _ast.Module) else "expr" if isinstance(obj, _ast.expr) else "stmt"
                return {"__type__": "ast", "src": _ast.unparse(obj), "cat": cat}
            import pathlib as _pl
            if isinstance(obj, _pl.PurePath):
                return {"__type__": "path", "s": str(obj)}
            return super().default(obj)

    
    def sandbox_decoder(dct):
        if "__type__" in dct:
            t = dct["__type__"]
            if t == "bytes":
                return bytes(dct["data"])
            if t == "set":
                return set(dct["data"])
            if t == "ast":
                import ast as _ast
                src, cat = dct["src"], dct.get("cat", "stmt")
                if cat == "mod":
                    return _ast.parse(src)
                if cat == "expr":
                    return _ast.parse(src, mode="eval").body
                return _ast.parse(src).body[0]
            if t == "path":
                import pathlib as _pl
                return _pl.Path(dct["s"])
        return dct

    def _set_child_limits(payload):
        sys.setrecursionlimit(payload.get("recursion_limit", 10000))
        stack_mb = payload.get("stack_mb", 64)
        stack_bytes = stack_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_STACK, (stack_bytes, stack_bytes))
        except ValueError:
            _, hard = resource.getrlimit(resource.RLIMIT_STACK)
            try:
                resource.setrlimit(resource.RLIMIT_STACK, (hard, hard))
            except ValueError:
                pass

        # FI-006 additions
        mem_mb = payload.get("memory_limit_mb", 256)
        cpu_sec = payload.get("cpu_time_limit_seconds", 10)
        fsize_mb = payload.get("child_fsize_limit_mb", 10)
        rlimit_nproc = payload.get("rlimit_nproc", None)

        mem_bytes = mem_mb * 1024 * 1024
        fsize_bytes = fsize_mb * 1024 * 1024
        for rlim, val in [(resource.RLIMIT_AS, mem_bytes),
                          (resource.RLIMIT_CPU, cpu_sec),
                          (resource.RLIMIT_FSIZE, fsize_bytes)]:
            try:
                resource.setrlimit(rlim, (val, val))
            except ValueError:
                pass

        if rlimit_nproc is not None:
            import warnings
            warnings.warn("Setting RLIMIT_NPROC can break Python threading inside the child. See test_nproc.py for details.", UserWarning)
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (rlimit_nproc, rlimit_nproc))
            except ValueError:
                pass

    import ctypes
    import ctypes.util

    _SECCOMP_LIB = None
    _SECCOMP_CTX_SETUP = False
    _SCMP_ACT_ERRNO_EPERM = 0x00050000 | 1
    _SCMP_ACT_ERRNO_ENOSYS = 0x00050000 | 38
    _BLOCKED_SYS_NOS = []
    _CLONE_SYS_NO = -1
    _CLONE3_SYS_NO = -1

    class scmp_arg_cmp(ctypes.Structure):
        _fields_ = [
            ("arg", ctypes.c_uint),
            ("op", ctypes.c_int),
            ("datum_a", ctypes.c_uint64),
            ("datum_b", ctypes.c_uint64),
        ]

    def _init_seccomp_globals():
        global _SECCOMP_LIB, _SECCOMP_CTX_SETUP, _BLOCKED_SYS_NOS, _CLONE_SYS_NO, _CLONE3_SYS_NO
        if _SECCOMP_CTX_SETUP:
            return
        
        lib_path = ctypes.util.find_library("seccomp")
        if not lib_path:
            return
        try:
            _SECCOMP_LIB = ctypes.CDLL(lib_path)
            _SECCOMP_LIB.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
            _SECCOMP_LIB.seccomp_syscall_resolve_name.restype = ctypes.c_int
            
            blocked_syscalls = [
                b"socket", b"connect", b"bind", b"listen", b"accept", b"accept4",
                b"fork", b"vfork", b"execve", b"execveat"
            ]
            for name in blocked_syscalls:
                sys_no = _SECCOMP_LIB.seccomp_syscall_resolve_name(name)
                if sys_no >= 0:
                    _BLOCKED_SYS_NOS.append(sys_no)
            
            _CLONE_SYS_NO = _SECCOMP_LIB.seccomp_syscall_resolve_name(b"clone")
            _CLONE3_SYS_NO = _SECCOMP_LIB.seccomp_syscall_resolve_name(b"clone3")
            
            _SECCOMP_CTX_SETUP = True
        except OSError:
            pass

    _init_seccomp_globals()


    def _install_seccomp():
        if not _SECCOMP_CTX_SETUP or not _SECCOMP_LIB:
            return

        _SECCOMP_LIB.seccomp_init.argtypes = [ctypes.c_uint32]
        _SECCOMP_LIB.seccomp_init.restype = ctypes.c_void_p
        ctx = _SECCOMP_LIB.seccomp_init(0x7fff0000)
        if not ctx:
            return

        _SECCOMP_LIB.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(scmp_arg_cmp)]
        _SECCOMP_LIB.seccomp_rule_add_array.restype = ctypes.c_int

        for sys_no in _BLOCKED_SYS_NOS:
            _SECCOMP_LIB.seccomp_rule_add_array(ctx, _SCMP_ACT_ERRNO_EPERM, sys_no, 0, None)

        if _CLONE_SYS_NO >= 0:
            SCMP_CMP_MASKED_EQ = 7
            CLONE_THREAD = 0x10000
            cmp = scmp_arg_cmp(0, SCMP_CMP_MASKED_EQ, CLONE_THREAD, 0)
            _SECCOMP_LIB.seccomp_rule_add_array(ctx, _SCMP_ACT_ERRNO_EPERM, _CLONE_SYS_NO, 1, ctypes.pointer(cmp))

        if _CLONE3_SYS_NO >= 0:
            _SECCOMP_LIB.seccomp_rule_add_array(ctx, _SCMP_ACT_ERRNO_ENOSYS, _CLONE3_SYS_NO, 0, None)

        _SECCOMP_LIB.seccomp_load.argtypes = [ctypes.c_void_p]
        _SECCOMP_LIB.seccomp_load.restype = ctypes.c_int
        _SECCOMP_LIB.seccomp_load(ctx)

        _SECCOMP_LIB.seccomp_release.argtypes = [ctypes.c_void_p]
        _SECCOMP_LIB.seccomp_release.restype = None
        _SECCOMP_LIB.seccomp_release(ctx)


    def main_single():
        import signal
        payload_path = sys.argv[1]
        with open(payload_path, "r") as f:
            payload = json.load(f, object_hook=sandbox_decoder)

        inputs = payload.get("inputs", [])
        if not inputs:
            return

        code = payload.get("code", "")
        func_name = payload.get("func_name", "")
        wall_timeout_per_input_sec = payload.get("wall_timeout_per_input_sec", 5.0)

        namespace = {}
        try:
            exec(compile(code, "<submission>", "exec"), namespace)
        except Exception as exc:
            for i in range(len(inputs)):
                err_record = {
                    "index": i,
                    "success": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "wall_time_ms": 0.0
                }
                print(json.dumps(err_record, ensure_ascii=False), flush=True)
            return

        func = namespace.get(func_name)
        if func is None:
            for i in range(len(inputs)):
                err_record = {
                    "index": i,
                    "success": False,
                    "exception_type": "NameError",
                    "exception_message": f"Function '{func_name}' not found in submission",
                    "wall_time_ms": 0.0
                }
                print(json.dumps(err_record, ensure_ascii=False), flush=True)
            return

        if inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func):
            # W101: async submissions silently produced (None, None) pairs in
            # the differential gate — refuse them at resolution time so a pair
            # of identical async submissions cannot match-as-equivalent on None.
            for i in range(len(inputs)):
                err_record = {
                    "index": i,
                    "success": False,
                    "exception_type": "TypeError",
                    "exception_message": f"async function '{func_name}' not supported in differential fuzz sandbox",
                    "wall_time_ms": 0.0
                }
                print(json.dumps(err_record, ensure_ascii=False), flush=True)
            return

        if payload.get("seccomp", True):
            _init_seccomp_globals()

        consecutive_timeouts = 0
        try:
            for i, inp in enumerate(inputs):
                call_args = inp.get("args", [])
                call_kwargs = inp.get("kwargs", {})
                
                pipe_r, pipe_w = os.pipe()
                pid = os.fork()
                
                if pid == 0:
                    os.close(pipe_r)
                    _set_child_limits(payload)
                    if payload.get("seccomp", True):
                        _install_seccomp()
                    
                    start = time.monotonic()
                    try:
                        ret = func(*call_args, **call_kwargs)
                        elapsed_ms = (time.monotonic() - start) * 1000
                        result = {
                            "index": i,
                            "success": True,
                            "return_repr": repr(ret),
                            "wall_time_ms": elapsed_ms,
                        }
                        try:
                            json.dumps(ret)
                            result["return_value"] = ret
                        except (TypeError, ValueError, OverflowError):
                            result["return_value"] = None
                    except Exception as exc:
                        elapsed_ms = (time.monotonic() - start) * 1000
                        result = {
                            "index": i,
                            "success": False,
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc),
                            "wall_time_ms": elapsed_ms,
                        }
                    
                    with os.fdopen(pipe_w, 'w') as f:
                        json.dump(result, f, ensure_ascii=False)
                        f.flush()
                    
                    os._exit(0)
                else:
                    os.close(pipe_w)
                    os.set_blocking(pipe_r, False)
                    
                    deadline = time.monotonic() + wall_timeout_per_input_sec
                    timed_out = False
                    wpid = 0
                    status = 0
                    pipe_data = b""
                    
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            timed_out = True
                            break
                            
                        try:
                            chunk = os.read(pipe_r, 65536)
                            if chunk:
                                pipe_data += chunk
                        except BlockingIOError:
                            pass
                            
                        wpid, status = os.waitpid(pid, os.WNOHANG)
                        if wpid != 0:
                            try:
                                while True:
                                    chunk = os.read(pipe_r, 65536)
                                    if not chunk:
                                        break
                                    pipe_data += chunk
                            except BlockingIOError:
                                pass
                            break
                        time.sleep(0.005)
                        
                    if timed_out:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except OSError:
                            pass
                        os.waitpid(pid, 0)
                        os.close(pipe_r)
                        err_record = {
                            "index": i,
                            "success": False,
                            "timed_out": True,
                            "exception_type": "TimeoutError",
                            "exception_message": f"Execution timed out after {wall_timeout_per_input_sec}s",
                            "wall_time_ms": wall_timeout_per_input_sec * 1000.0
                        }
                        print(json.dumps(err_record, ensure_ascii=False), flush=True)
                        consecutive_timeouts += 1
                        if consecutive_timeouts >= 20:
                            sys.exit(0)
                        continue
                        
                    try:
                        os.close(pipe_r)
                    except OSError:
                        pass
                        
                    is_valid_json = False
                    decoded_str = ""
                    if pipe_data.strip():
                        try:
                            decoded_str = pipe_data.decode('utf-8')
                            json.loads(decoded_str)
                            is_valid_json = True
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            pass
                            
                    if is_valid_json:
                        print(decoded_str.strip(), flush=True)
                        consecutive_timeouts = 0
                        continue
                        
                    # Not valid JSON or empty. Handle signals and errors.
                    if os.WIFSIGNALED(status):
                        sig = os.WTERMSIG(status)
                        if sig in (signal.SIGKILL, signal.SIGXCPU):
                            err_record = {
                                "index": i,
                                "success": False,
                                "timed_out": True,
                                "exception_type": "TimeoutError",
                                "exception_message": f"Child killed by signal {sig} (SIGXCPU/SIGKILL)",
                                "wall_time_ms": 0.0
                            }
                        else:
                            err_record = {
                                "index": i,
                                "success": False,
                                "exception_type": "SandboxError",
                                "exception_message": f"Child killed: {sig}",
                                "wall_time_ms": 0.0
                            }
                    else:
                        if not pipe_data.strip():
                            err_record = {
                                "index": i,
                                "success": False,
                                "exception_type": "SandboxError",
                                "exception_message": "Child exited without writing result",
                                "wall_time_ms": 0.0
                            }
                        else:
                            err_record = {
                                "index": i,
                                "success": False,
                                "exception_type": "SandboxError",
                                "exception_message": "Corrupt result from child",
                                "wall_time_ms": 0.0
                            }
                            
                    print(json.dumps(err_record, ensure_ascii=False), flush=True)
                    if err_record.get("timed_out"):
                        consecutive_timeouts += 1
                        if consecutive_timeouts >= 20:
                            sys.exit(0)
                    else:
                        consecutive_timeouts = 0
        finally:
            while True:
                try:
                    wpid, _ = os.waitpid(-1, os.WNOHANG)
                    if wpid <= 0:
                        break
                except ChildProcessError:
                    break
                except OSError:
                    break


    def main_pool():
        import signal
        import struct
        
        while True:
            try:
                length_bytes = sys.stdin.buffer.read(4)
            except Exception:
                break
            if not length_bytes:
                break
            if len(length_bytes) < 4:
                sys.exit(1)
            
            payload_len = struct.unpack(">I", length_bytes)[0]
            payload_bytes = sys.stdin.buffer.read(payload_len)
            if len(payload_bytes) < payload_len:
                sys.exit(1)
                
            payload = json.loads(payload_bytes.decode('utf-8'))
            
            inputs = payload.get("inputs", [])
            if not inputs:
                batch_done_msg = b'{"status": "batch_done"}'
                sys.stdout.buffer.write(struct.pack(">I", len(batch_done_msg)))
                sys.stdout.buffer.write(batch_done_msg)
                sys.stdout.buffer.flush()
                continue
                
            code = payload.get("code", "")
            func_name = payload.get("func_name", "")
            wall_timeout_per_input_sec = payload.get("wall_timeout_per_input_sec", 5.0)

            namespace = {}
            compile_err = None
            try:
                exec(compile(code, "<submission>", "exec"), namespace)
            except Exception as exc:
                compile_err = exc
                
            func = namespace.get(func_name)
            if compile_err is None and func is None:
                compile_err = NameError(f"Function '{func_name}' not found in submission")
            if compile_err is None and (inspect.iscoroutinefunction(func) or inspect.isasyncgenfunction(func)):
                # Same silent-pass guard as main_single: refuse async submissions
                # so a differential-fuzz pair cannot falsely match on None.
                compile_err = TypeError(f"async function '{func_name}' not supported in differential fuzz sandbox")

            if compile_err is not None:
                for i in range(len(inputs)):
                    err_record = {
                        "index": i,
                        "success": False,
                        "exception_type": type(compile_err).__name__,
                        "exception_message": str(compile_err),
                        "wall_time_ms": 0.0
                    }
                    record_bytes = json.dumps(err_record, ensure_ascii=False).encode('utf-8')
                    sys.stdout.buffer.write(struct.pack(">I", len(record_bytes)))
                    sys.stdout.buffer.write(record_bytes)
                    sys.stdout.buffer.flush()
                
                batch_done_msg = b'{"status": "batch_done"}'
                sys.stdout.buffer.write(struct.pack(">I", len(batch_done_msg)))
                sys.stdout.buffer.write(batch_done_msg)
                sys.stdout.buffer.flush()
                continue
                
            try:
                for i, inp in enumerate(inputs):
                    call_args = inp.get("args", [])
                    call_kwargs = inp.get("kwargs", {})
                    
                    pipe_r, pipe_w = os.pipe()
                    pid = os.fork()
                    
                    if pid == 0:
                        os.close(pipe_r)
                        _set_child_limits(payload)
                        if payload.get("seccomp", True):
                            _install_seccomp()
                        
                        start = time.monotonic()
                        try:
                            ret = func(*call_args, **call_kwargs)
                            elapsed_ms = (time.monotonic() - start) * 1000
                            result = {
                                "index": i,
                                "success": True,
                                "return_repr": repr(ret),
                                "wall_time_ms": elapsed_ms,
                            }
                            try:
                                json.dumps(ret)
                                result["return_value"] = ret
                            except (TypeError, ValueError, OverflowError):
                                result["return_value"] = None
                        except Exception as exc:
                            elapsed_ms = (time.monotonic() - start) * 1000
                            result = {
                                "index": i,
                                "success": False,
                                "exception_type": type(exc).__name__,
                                "exception_message": str(exc),
                                "wall_time_ms": elapsed_ms,
                            }
                        
                        with os.fdopen(pipe_w, 'w') as f:
                            json.dump(result, f, ensure_ascii=False)
                            f.flush()
                        
                        os._exit(0)
                    else:
                        os.close(pipe_w)
                        os.set_blocking(pipe_r, False)
                        
                        deadline = time.monotonic() + wall_timeout_per_input_sec
                        timed_out = False
                        wpid = 0
                        status = 0
                        pipe_data = b""
                        
                        while True:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                timed_out = True
                                break
                                
                            try:
                                chunk = os.read(pipe_r, 65536)
                                if chunk:
                                    pipe_data += chunk
                            except BlockingIOError:
                                pass
                                
                            wpid, status = os.waitpid(pid, os.WNOHANG)
                            if wpid != 0:
                                try:
                                    while True:
                                        chunk = os.read(pipe_r, 65536)
                                        if not chunk:
                                            break
                                        pipe_data += chunk
                                except BlockingIOError:
                                    pass
                                break
                            time.sleep(0.005)
                            
                        if timed_out:
                            try:
                                os.kill(pid, signal.SIGKILL)
                            except OSError:
                                pass
                            os.waitpid(pid, 0)
                            os.close(pipe_r)
                            err_record = {
                                "index": i,
                                "success": False,
                                "timed_out": True,
                                "exception_type": "TimeoutError",
                                "exception_message": f"Execution timed out after {wall_timeout_per_input_sec}s",
                                "wall_time_ms": wall_timeout_per_input_sec * 1000.0
                            }
                            record_bytes = json.dumps(err_record, ensure_ascii=False).encode('utf-8')
                            sys.stdout.buffer.write(struct.pack(">I", len(record_bytes)))
                            sys.stdout.buffer.write(record_bytes)
                            sys.stdout.buffer.flush()
                            continue
                            
                        try:
                            os.close(pipe_r)
                        except OSError:
                            pass
                            
                        is_valid_json = False
                        decoded_str = ""
                        if pipe_data.strip():
                            try:
                                decoded_str = pipe_data.decode('utf-8')
                                json.loads(decoded_str)
                                is_valid_json = True
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                pass
                                
                        if is_valid_json:
                            record_bytes = decoded_str.strip().encode('utf-8')
                            sys.stdout.buffer.write(struct.pack(">I", len(record_bytes)))
                            sys.stdout.buffer.write(record_bytes)
                            sys.stdout.buffer.flush()
                            continue
                            
                        if os.WIFSIGNALED(status):
                            sig = os.WTERMSIG(status)
                            if sig in (signal.SIGKILL, signal.SIGXCPU):
                                err_record = {
                                    "index": i,
                                    "success": False,
                                    "timed_out": True,
                                    "exception_type": "TimeoutError",
                                    "exception_message": f"Child killed by signal {sig} (SIGXCPU/SIGKILL)",
                                    "wall_time_ms": 0.0
                                }
                            else:
                                err_record = {
                                    "index": i,
                                    "success": False,
                                    "exception_type": "SandboxError",
                                    "exception_message": f"Child killed: {sig}",
                                    "wall_time_ms": 0.0
                                }
                        else:
                            if not pipe_data.strip():
                                err_record = {
                                    "index": i,
                                    "success": False,
                                    "exception_type": "SandboxError",
                                    "exception_message": "Child exited without writing result",
                                    "wall_time_ms": 0.0
                                }
                            else:
                                err_record = {
                                    "index": i,
                                    "success": False,
                                    "exception_type": "SandboxError",
                                    "exception_message": "Corrupt result from child",
                                    "wall_time_ms": 0.0
                                }
                                
                        record_bytes = json.dumps(err_record, ensure_ascii=False).encode('utf-8')
                        sys.stdout.buffer.write(struct.pack(">I", len(record_bytes)))
                        sys.stdout.buffer.write(record_bytes)
                        sys.stdout.buffer.flush()
            finally:
                while True:
                    try:
                        wpid, _ = os.waitpid(-1, os.WNOHANG)
                        if wpid <= 0:
                            break
                    except ChildProcessError:
                        break
                    except OSError:
                        break

            batch_done_msg = b'{"status": "batch_done"}'
            sys.stdout.buffer.write(struct.pack(">I", len(batch_done_msg)))
            sys.stdout.buffer.write(batch_done_msg)
            sys.stdout.buffer.flush()


    if __name__ == "__main__":
        if len(sys.argv) > 1 and sys.argv[1] == "--pool":
            main_pool()
        else:
            main_single()

""")


# ---------------------------------------------------------------------------
# Process Management & Watchdog
# ---------------------------------------------------------------------------

def kill_process_group(pid: int, grace_sec: float = 0.2) -> None:
    """Kill a process group gracefully, then forcefully."""
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return  # Already dead
    except PermissionError as e:
        print(f"Warning: kill_process_group permission error on pid {pid}: {e}", file=sys.stderr)
        return

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        pass
    
    time.sleep(grace_sec)
    
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        pass


class WallDeadlineWatchdog:
    """Kills a process group if a wall-clock deadline is exceeded."""

    def __init__(self, pid: int, deadline_sec: float, on_expire: Callable[[int], None] | None = None):
        self.pid = pid
        self.deadline_sec = deadline_sec
        self.on_expire = on_expire or kill_process_group
        self._cancel_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        # Wait until deadline or cancel
        if not self._cancel_event.wait(self.deadline_sec):
            # Timeout expired without being cancelled
            try:
                self.on_expire(self.pid)
            except Exception as e:
                print(f"Watchdog on_expire raised: {e}", file=sys.stderr)

    def cancel(self) -> None:
        self._cancel_event.set()


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------


def _safe_close_proc(proc: subprocess.Popen | None) -> None:
    """Safely close a subprocess's pipes and wait for it to exit."""
    if proc is None:
        return
    for pipe in (proc.stdout, proc.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except Exception:
                pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.waitpid(-1, os.WNOHANG)
        except OSError:
            pass

class Sandbox:
    """Manages isolated execution of code samples."""

    def __init__(self, config: SandboxConfig | None = None, session_id: str = "default"):
        self.config = config or SandboxConfig()
        self.session_id = session_id
        self._sandbox_dir: Path | None = None

    @property
    def sandbox_dir(self) -> Path:
        if self._sandbox_dir is None:
            root = Path(self.config.filesystem_root)
            self._sandbox_dir = root / f"session_{self.session_id}"
            self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        return self._sandbox_dir

    def cleanup(self) -> None:
        """Remove the sandbox directory."""
        if self._sandbox_dir is not None and self._sandbox_dir.exists():
            shutil.rmtree(self._sandbox_dir, ignore_errors=True)
            self._sandbox_dir = None

    def execute(
        self,
        code: str,
        func_name: str,
        args: list | None = None,
        kwargs: dict | None = None,
    ) -> ExecutionResult:
        """Execute a function from *code* with the given arguments in a sandbox.

        The code is compiled and the named function is called in an isolated
        subprocess with resource limits enforced.
        """
        args = args if args is not None else []
        kwargs = kwargs if kwargs is not None else {}

        work_dir = self.sandbox_dir / "work"
        work_dir.mkdir(parents=True, exist_ok=True)

        # Write runner script
        runner_path = work_dir / "_runner.py"
        runner_path.write_text(_RUNNER_TEMPLATE)

        # Write payload
        payload = {
            "code": code,
            "func_name": func_name,
            "args": args,
            "kwargs": kwargs,
            "memory_limit_mb": self.config.memory_limit_mb,
            "cpu_time_limit_seconds": self.config.cpu_time_limit_seconds,
            "recursion_limit": self.config.recursion_limit,
            "stack_mb": self.config.stack_mb,
        }
        payload_path = work_dir / "_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, cls=SandboxEncoder))

        # Result file
        result_path = work_dir / "_result.json"
        if result_path.exists():
            result_path.unlink()

        # Calculate wall timeout: per-input timeout + 2s grace for startup
        wall_timeout = (self.config.timeout_per_input_ms / 1000) + 2.0

        env = sandbox_child_env({
            "PYTHONHASHSEED": self.config.python_hash_seed,
            "HOME": str(work_dir),
            "TMPDIR": str(work_dir),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        })

        # Use Popen with a new session so we can kill the entire process
        # group on timeout (necessary for fork bombs and runaway children).
        proc = None
        proc_stderr = ""
        try:
            proc = subprocess.Popen(
                [sys.executable, str(runner_path), str(payload_path), str(result_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=str(work_dir),
                start_new_session=True,
            )
            
            watchdog = WallDeadlineWatchdog(proc.pid, wall_timeout)
            try:
                stdout, stderr = proc.communicate(timeout=wall_timeout)
            except subprocess.TimeoutExpired:
                # Watchdog will have fired or is firing.
                # Do a fallback kill just in case, but it's largely a no-op now.
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.kill()
                _safe_close_proc(proc)
                return ExecutionResult(
                    success=False,
                    timed_out=True,
                    exception_type="TimeoutError",
                    exception_message=f"Execution timed out after {wall_timeout:.1f}s",
                )
            finally:
                watchdog.cancel()

            proc_stderr = stderr
        except OSError as e:
            return ExecutionResult(
                success=False,
                exception_type="SandboxError",
                exception_message=f"Failed to start sandbox process: {e}",
            )
        finally:
            if proc is not None:
                _safe_close_proc(proc)

        # Read result
        if not result_path.exists():
            # Detect CPU time limit kills: SIGKILL (-9) or SIGXCPU (-24)
            # from resource.RLIMIT_CPU enforcement.
            if proc.returncode in (-9, -24):
                return ExecutionResult(
                    success=False,
                    timed_out=True,
                    exception_type="TimeoutError",
                    exception_message=f"Execution killed by CPU time limit "
                                      f"(signal {-proc.returncode})",
                    stderr=proc_stderr,
                )
            return ExecutionResult(
                success=False,
                exception_type="SandboxError",
                exception_message=f"Runner did not produce result file. "
                                  f"returncode={proc.returncode} stderr={proc_stderr[:500]}",
                stderr=proc_stderr,
            )

        try:
            with open(result_path, "r") as f:
                result_data = json.load(f, object_hook=sandbox_decoder)
        except (json.JSONDecodeError, ValueError) as exc:
            return ExecutionResult(
                success=False,
                exception_type="SandboxError",
                exception_message=f"Corrupt result file: {exc}",
                stderr=proc_stderr,
            )

        return ExecutionResult(
            success=result_data.get("success", False),
            return_value=result_data.get("return_value"),
            return_repr=result_data.get("return_repr", ""),
            exception_type=result_data.get("exception_type"),
            exception_message=result_data.get("exception_message"),
            timed_out=False,
            stderr=proc_stderr,
            wall_time_ms=result_data.get("wall_time_ms", 0.0),
        )


def sandbox_from_config(config: dict[str, Any], session_id: str = "default") -> Sandbox:
    """Create a Sandbox from a harness config dict (the 'sandbox' section)."""
    sandbox_cfg = config.get("sandbox", {})
    return Sandbox(
        config=SandboxConfig(
            memory_limit_mb=sandbox_cfg.get("memory_limit_mb", 256),
            cpu_time_limit_seconds=sandbox_cfg.get("cpu_time_limit_seconds", 10),
            timeout_per_input_ms=config.get("fuzzing", {}).get("timeout_per_input_ms", 5000),
            filesystem_root=sandbox_cfg.get("filesystem_root", "/tmp/janusmask_sandbox"),
            python_hash_seed=str(config.get("fuzzing", {}).get("seed", 42)),
            recursion_limit=sandbox_cfg.get("recursion_limit", 10000),
            stack_mb=sandbox_cfg.get("stack_mb", 64),
        ),
        session_id=session_id,
    )


class BatchRunner:
    """Runs batches of inputs in isolated subprocesses."""

    def __init__(self, config: SandboxConfig | None = None, session_id: str = "default"):
        self.config = config or SandboxConfig()
        self.session_id = session_id
        self._sandbox_dir: Path | None = None
        self._sandbox_fallback = Sandbox(config=self.config, session_id=f"{self.session_id}_fallback")

    @property
    def sandbox_dir(self) -> Path:
        if self._sandbox_dir is None:
            root = Path(self.config.filesystem_root)
            self._sandbox_dir = root / f"session_{self.session_id}"
            self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        return self._sandbox_dir

    def cleanup(self) -> None:
        """Remove the sandbox directory."""
        if self._sandbox_dir is not None and self._sandbox_dir.exists():
            shutil.rmtree(self._sandbox_dir, ignore_errors=True)
            self._sandbox_dir = None
        self._sandbox_fallback.cleanup()

    def execute_batch(
        self,
        code: str,
        func_name: str,
        inputs: list[dict],
    ) -> BatchResult:
        if not inputs:
            return BatchResult(
                results=[],
                total_inputs=0,
                completed_inputs=0,
                batch_error=None
            )

        results = [
            ExecutionResult(
                success=False,
                exception_type="SandboxError",
                exception_message="No result received",
            ) for _ in range(len(inputs))
        ]

        work_dir = self.sandbox_dir / "work"
        work_dir.mkdir(parents=True, exist_ok=True)

        runner_path = work_dir / "runner.py"
        runner_path.write_text(_BATCH_RUNNER_TEMPLATE)

        payload_path = work_dir / "payload.json"
        
        per_input_timeout = self.config.timeout_per_input_ms / 1000.0
        
        payload = {
            "code": code,
            "func_name": func_name,
            "inputs": inputs,
            "memory_limit_mb": self.config.memory_limit_mb,
            "cpu_time_limit_seconds": self.config.cpu_time_limit_seconds,
            "recursion_limit": self.config.recursion_limit,
            "stack_mb": self.config.stack_mb,
            "wall_timeout_per_input_sec": per_input_timeout,
        }
        with open(payload_path, "w") as f:
            json.dump(payload, f, ensure_ascii=False, cls=SandboxEncoder)

        total_wall_timeout = min(len(inputs) * per_input_timeout + 10, 1800)

        env = sandbox_child_env({
            "PYTHONHASHSEED": self.config.python_hash_seed,
            "HOME": str(work_dir),
            "TMPDIR": str(work_dir),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        })

        proc = None
        completed_inputs = 0
        batch_error = None

        try:
            proc = subprocess.Popen(
                [sys.executable, str(runner_path), str(payload_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=str(work_dir),
                start_new_session=True,
            )
            
            watchdog = WallDeadlineWatchdog(proc.pid, total_wall_timeout)
            
            try:
                for line in proc.stdout:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line, object_hook=sandbox_decoder)
                        idx = record.get("index")
                        if idx is not None and 0 <= idx < len(inputs):
                            results[idx] = ExecutionResult(
                                success=record.get("success", False),
                                return_value=record.get("return_value"),
                                return_repr=record.get("return_repr", ""),
                                exception_type=record.get("exception_type"),
                                exception_message=record.get("exception_message"),
                                timed_out=record.get("timed_out", False),
                                wall_time_ms=record.get("wall_time_ms", 0.0),
                            )
                            completed_inputs += 1
                    except json.JSONDecodeError:
                        pass
                proc.wait(timeout=total_wall_timeout)
                if proc.returncode != 0:
                    batch_error = f"Runner process exited with code {proc.returncode}"
            except subprocess.TimeoutExpired:
                batch_error = f"Batch execution timed out after {total_wall_timeout:.1f}s"
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    pass
                proc.wait(timeout=5)
            except Exception as e:
                batch_error = f"Error during batch execution: {e}"
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    pass
                proc.wait(timeout=5)
            finally:
                watchdog.cancel()
        except OSError as e:
            batch_error = f"Failed to start batch runner: {e}"
        finally:
            if proc is not None:
                _safe_close_proc(proc)

        return BatchResult(
            results=results,
            total_inputs=len(inputs),
            completed_inputs=completed_inputs,
            batch_error=batch_error
        )


_STATEFUL_TRACE_DRIVER = '\n\ndef __janusmask_replay_trace__(class_name, init_args, method_calls):\n    import json as _json\n\n    def _safe_repr(v):\n        try:\n            return repr(v)\n        except Exception:\n            return "<unreprable>"\n\n    def _split_args(container):\n        if container is None:\n            return [], {}\n        if isinstance(container, dict):\n            if "args" in container or "kwargs" in container:\n                a = container.get("args", [])\n                k = container.get("kwargs", {})\n                a = list(a) if a is not None else []\n                k = dict(k) if k is not None else {}\n                return a, k\n            return [], dict(container)\n        if isinstance(container, (list, tuple)):\n            return list(container), {}\n        return [container], {}\n\n    def _method_of(call):\n        if isinstance(call, dict):\n            return (call.get("method") or call.get("name")), call\n        if isinstance(call, (list, tuple)):\n            name = call[0] if len(call) >= 1 else None\n            cargs = call[1] if len(call) >= 2 else None\n            return name, cargs\n        return call, None\n\n    def _serialize(value):\n        try:\n            _json.dumps(value)\n            return value, True\n        except Exception:\n            return None, False\n\n    calls = list(method_calls or [])\n    trace = []\n\n    cls = globals().get(class_name)\n    if cls is None:\n        trace.append({\n            "step": 0,\n            "method": "__init__",\n            "exception": {"type": "NameError",\n                          "message": "class \'%s\' not found in submission" % class_name},\n        })\n        for i, call in enumerate(calls, start=1):\n            mname, _c = _method_of(call)\n            trace.append({"step": i, "method": mname,\n                          "skipped": True, "reason": "class_not_found"})\n        return trace\n\n    ia, ik = _split_args(init_args)\n    try:\n        instance = cls(*ia, **ik)\n    except Exception as exc:\n        trace.append({\n            "step": 0,\n            "method": "__init__",\n            "exception": {"type": type(exc).__name__, "message": str(exc)},\n        })\n        for i, call in enumerate(calls, start=1):\n            mname, _c = _method_of(call)\n            trace.append({"step": i, "method": mname,\n                          "skipped": True, "reason": "construction_failed"})\n        return trace\n\n    trace.append({"step": 0, "method": "__init__",\n                  "value": None, "value_repr": _safe_repr(instance)})\n\n    for i, call in enumerate(calls, start=1):\n        mname, cargs = _method_of(call)\n        ca, ck = _split_args(cargs)\n        try:\n            method = getattr(instance, mname)\n            ret = method(*ca, **ck)\n        except Exception as exc:\n            trace.append({"step": i, "method": mname,\n                          "exception": {"type": type(exc).__name__,\n                                        "message": str(exc)}})\n            continue\n        sval, ok = _serialize(ret)\n        trace.append({"step": i, "method": mname,\n                      "value": sval if ok else None,\n                      "value_repr": _safe_repr(ret)})\n\n    return trace\n'

def execute_stateful_trace(code: str, class_name: str, init_args: Any=None, method_calls: list | None=None, *, runner: Any=None, timeout: float | None=None) -> list[dict]:
    """Replay a symbolic action sequence against a freshly-built instance.

    The class named *class_name* (defined in *code*) is instantiated with
    *init_args*, then each ``(method_name, args)`` entry in *method_calls* is
    invoked in order against the single living instance. Each step is captured
    as either ``{'step': i, 'method': name, 'value': ..., 'value_repr': ...}``
    or ``{'step': i, 'method': name, 'exception': {'type': ..., 'message': ...}}``.
    Step 0 is the constructor result; if construction raises, the failure is
    recorded at step 0 and the remaining steps are marked ``skipped`` (not run),
    so the total length is always ``len(method_calls) + 1``.

    The replay executes through the existing :class:`Sandbox` (or a supplied
    *runner* exposing a compatible ``execute``), so every credential /
    environment / nondeterminism / resource gate of the jail is inherited
    unchanged -- this routine only *calls* the sandbox, it does not alter it.
    Constructor failures, per-step exceptions, timeouts and jail kills are all
    surfaced as structured trace entries rather than raised. The returned list
    is plain JSON-compatible data suitable for ``outputs_match`` / ``_deep_compare``.

    Args:
        code: Implementation source defining the class under test.
        class_name: Name of the class to instantiate.
        init_args: Constructor arguments; a list/tuple (positional), a dict
            (keyword), or a ``{'args': [...], 'kwargs': {...}}`` container.
        method_calls: Ordered ``(method_name, args)`` commands; each entry may
            be a ``[name, args]`` pair, a ``{'method': name, 'args': ...}`` dict,
            or a bare method-name string.
        runner: Optional pre-built ``Sandbox``/``BatchRunner`` to reuse instead
            of constructing a throwaway ``Sandbox``.
        timeout: Optional per-execution wall budget in seconds (only applied
            when this function builds its own ``Sandbox``).
    """
    calls = list(method_calls or [])

    def _name_of(call: Any) -> Any:
        if isinstance(call, dict):
            return call.get('method') or call.get('name')
        if isinstance(call, (list, tuple)):
            return call[0] if call else None
        return call

    def _failed_trace(err_type: str, err_msg: str, reason: str) -> list[dict]:
        out: list[dict] = [{'step': 0, 'method': '__init__', 'exception': {'type': err_type, 'message': err_msg}}]
        for i, call in enumerate(calls, start=1):
            out.append({'step': i, 'method': _name_of(call), 'skipped': True, 'reason': reason})
        return out
    driver_src = code + '\n\n' + _STATEFUL_TRACE_DRIVER
    own_runner = False
    if runner is None:
        cfg = SandboxConfig()
        if timeout is not None:
            cfg.timeout_per_input_ms = int(float(timeout) * 1000)
        session = f'stateful_trace_{os.getpid()}_{int(time.time() * 1000000)}'
        runner = Sandbox(config=cfg, session_id=session)
        own_runner = True
    execute = getattr(runner, 'execute', None)
    if not callable(execute):
        fallback = getattr(runner, '_sandbox_fallback', None)
        execute = getattr(fallback, 'execute', None)
    if not callable(execute):
        return _failed_trace('SandboxError', 'runner does not support single execution', 'sandbox_error')
    try:
        result = execute(driver_src, '__janusmask_replay_trace__', [class_name, init_args, calls])
    except Exception as exc:
        return _failed_trace(type(exc).__name__, str(exc), 'sandbox_error')
    finally:
        if own_runner:
            try:
                runner.cleanup()
            except Exception:
                pass
    if getattr(result, 'success', False) and isinstance(getattr(result, 'return_value', None), list):
        return result.return_value
    if getattr(result, 'timed_out', False):
        return _failed_trace('TimeoutError', getattr(result, 'exception_message', None) or 'stateful trace timed out', 'timed_out')
    err_type = getattr(result, 'exception_type', None) or 'SandboxError'
    err_msg = getattr(result, 'exception_message', None) or 'stateful trace execution failed'
    return _failed_trace(err_type, err_msg, 'sandbox_error')
def batch_runner_from_config(config: dict[str, Any], session_id: str = "default") -> BatchRunner:
    """Create a BatchRunner from a harness config dict (the 'sandbox' section)."""
    sandbox_cfg = config.get("sandbox", {})
    batch_cfg = config.get("batch_execution", {})
    return BatchRunner(
        config=SandboxConfig(
            memory_limit_mb=sandbox_cfg.get("memory_limit_mb", 256),
            cpu_time_limit_seconds=sandbox_cfg.get("cpu_time_limit_seconds", 10),
            timeout_per_input_ms=config.get("fuzzing", {}).get("timeout_per_input_ms", 5000),
            filesystem_root=sandbox_cfg.get("filesystem_root", "/tmp/janusmask_sandbox"),
            python_hash_seed=str(config.get("fuzzing", {}).get("seed", 42)),
            recursion_limit=sandbox_cfg.get("recursion_limit", 10000),
            stack_mb=sandbox_cfg.get("stack_mb", 64),
            seccomp=batch_cfg.get("seccomp", True),
            rlimit_nproc=batch_cfg.get("rlimit_nproc", None),
        ),
        session_id=session_id,
    )



class BatchWorkerPool:
    """Persistent pool of batch-runner subprocesses."""

    def __init__(self, size: int, config: SandboxConfig | None = None, session_id: str = "pool"):
        self.size = max(1, size)
        self.config = config or SandboxConfig()
        self.session_id = session_id
        
        root = Path(self.config.filesystem_root)
        self._sandbox_dir = root / f"session_{self.session_id}"
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        
        self._workers = []
        self._available_workers = queue.Queue()
        self._lock = threading.Lock()
        self._shutting_down = False
        
        for i in range(self.size):
            worker = self._spawn_worker(i)
            with self._lock:
                self._workers.append(worker)
            self._available_workers.put(worker)

    def _spawn_worker(self, worker_id: int):
        work_dir = self._sandbox_dir / f"worker_{worker_id}"
        work_dir.mkdir(parents=True, exist_ok=True)
        
        runner_path = work_dir / "runner.py"
        runner_path.write_text(_BATCH_RUNNER_TEMPLATE)
        
        env = sandbox_child_env({
            "PYTHONHASHSEED": self.config.python_hash_seed,
            "HOME": str(work_dir),
            "TMPDIR": str(work_dir),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        })
        
        proc = subprocess.Popen(
            [sys.executable, str(runner_path), "--pool"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(work_dir),
            start_new_session=True,
        )
        
        return {
            "proc": proc,
            "work_dir": work_dir,
            "id": worker_id,
            "lock": threading.Lock()
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()

    def shutdown(self):
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            
        # Empty the queue so no new submits are accepted
        while not self._available_workers.empty():
            try:
                self._available_workers.get_nowait()
            except queue.Empty:
                break
                
        workers_to_kill = []
        with self._lock:
            workers_to_kill = list(self._workers)
            self._workers.clear()

        for worker in workers_to_kill:
            proc = worker["proc"]
            if proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            kill_process_group(proc.pid, grace_sec=1.0)
            _safe_close_proc(proc)

    def submit(self, code: str, func_name: str, inputs: list[dict]) -> BatchResult:
        if not inputs:
            return BatchResult(results=[], total_inputs=0, completed_inputs=0, batch_error=None)
            
        with self._lock:
            if self._shutting_down:
                return BatchResult(
                    results=[],
                    total_inputs=len(inputs),
                    completed_inputs=0,
                    batch_error="pool shutting down"
                )

        try:
            worker = self._available_workers.get(timeout=None)
        except queue.Empty:
            return BatchResult(
                results=[],
                total_inputs=len(inputs),
                completed_inputs=0,
                batch_error="pool shutting down"
            )
            
        with self._lock:
            if self._shutting_down:
                return BatchResult(
                    results=[],
                    total_inputs=len(inputs),
                    completed_inputs=0,
                    batch_error="pool shutting down"
                )

        try:
            with worker["lock"]:
                return self._submit_to_worker(worker, code, func_name, inputs)
        finally:
            with self._lock:
                if not self._shutting_down:
                    self._available_workers.put(worker)

    def _submit_to_worker(self, worker, code: str, func_name: str, inputs: list[dict]) -> BatchResult:
        proc = worker["proc"]
        
        per_input_timeout = self.config.timeout_per_input_ms / 1000.0
        payload = {
            "code": code,
            "func_name": func_name,
            "inputs": inputs,
            "memory_limit_mb": self.config.memory_limit_mb,
            "cpu_time_limit_seconds": self.config.cpu_time_limit_seconds,
            "recursion_limit": self.config.recursion_limit,
            "stack_mb": self.config.stack_mb,
            "wall_timeout_per_input_sec": per_input_timeout,
            "seccomp": self.config.seccomp if hasattr(self.config, 'seccomp') else True
        }
        
        payload_bytes = json.dumps(payload, ensure_ascii=False, cls=SandboxEncoder).encode('utf-8')
        
        results = [
            ExecutionResult(
                success=False,
                exception_type="SandboxError",
                exception_message="No result received",
            ) for _ in range(len(inputs))
        ]
        
        try:
            # Send framing
            proc.stdin.write(struct.pack(">I", len(payload_bytes)))
            proc.stdin.write(payload_bytes)
            proc.stdin.flush()
        except OSError as e:
            self._respawn_worker(worker)
            return BatchResult(
                results=results,
                total_inputs=len(inputs),
                completed_inputs=0,
                batch_error=f"Worker write failed: {e}"
            )
            
        completed_inputs = 0
        batch_error = None
        
        total_wall_timeout = min(len(inputs) * per_input_timeout + 10, 1800)
        
        # Read frames until batch_done
        deadline = time.monotonic() + total_wall_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                batch_error = f"Batch execution timed out after {total_wall_timeout:.1f}s"
                self._respawn_worker(worker)
                break
                
            try:
                # Read length prefix
                length_bytes = self._read_exactly(proc.stdout, 4, deadline, proc.pid)
                if not length_bytes or len(length_bytes) < 4:
                    batch_error = "Worker stdout closed unexpectedly mid-batch"
                    self._respawn_worker(worker)
                    break
                    
                frame_len = struct.unpack(">I", length_bytes)[0]
                frame_bytes = self._read_exactly(proc.stdout, frame_len, deadline, proc.pid)
                if not frame_bytes or len(frame_bytes) < frame_len:
                    batch_error = "Worker stdout closed unexpectedly reading frame"
                    self._respawn_worker(worker)
                    break
                    
                record = json.loads(frame_bytes.decode('utf-8'))
                if record.get("status") == "batch_done":
                    break
                    
                idx = record.get("index")
                if idx is not None and 0 <= idx < len(inputs):
                    results[idx] = ExecutionResult(
                        success=record.get("success", False),
                        return_value=record.get("return_value"),
                        return_repr=record.get("return_repr", ""),
                        exception_type=record.get("exception_type"),
                        exception_message=record.get("exception_message"),
                        timed_out=record.get("timed_out", False),
                        wall_time_ms=record.get("wall_time_ms", 0.0),
                    )
                    completed_inputs += 1
                    
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                batch_error = f"Corrupt frame received from worker: {e}"
                self._respawn_worker(worker)
                break
            except Exception as e:
                batch_error = f"Error reading from worker: {e}"
                self._respawn_worker(worker)
                break
                
        return BatchResult(
            results=results,
            total_inputs=len(inputs),
            completed_inputs=completed_inputs,
            batch_error=batch_error
        )

    def _read_exactly(self, pipe, count: int, deadline: float, pid: int) -> bytes:
        import os, select, time
        fd = pipe.fileno()
        os.set_blocking(fd, False)
        data = b""
        while len(data) < count:
            if time.monotonic() > deadline:
                break
            try:
                chunk = os.read(fd, count - len(data))
                if not chunk:
                    break
                data += chunk
            except BlockingIOError:
                r, _, _ = select.select([fd], [], [], 0.05)
                if not r:
                    try:
                        wpid, _ = os.waitpid(pid, os.WNOHANG)
                        if wpid == pid:
                            break
                    except ChildProcessError:
                        break
        return data

    def _respawn_worker(self, worker):
        with self._lock:
            if self._shutting_down:
                return
        proc = worker["proc"]
        kill_process_group(proc.pid, grace_sec=0.1)
        _safe_close_proc(proc)
        
        new_worker_info = self._spawn_worker(worker["id"])
        worker["proc"] = new_worker_info["proc"]


_global_fuzzing_pool = None
_global_fuzzing_pool_lock = threading.Lock()

def get_global_pool(config: dict | SandboxConfig) -> BatchWorkerPool:
    global _global_fuzzing_pool
    with _global_fuzzing_pool_lock:
        if isinstance(config, dict):
            target_size = config.get("batch_execution", {}).get("worker_pool_size", 1)
            sandbox_cfg = sandbox_from_config(config).config
        else:
            target_size = getattr(config, "worker_pool_size", 1)
            sandbox_cfg = config

        if _global_fuzzing_pool is not None:
            if _global_fuzzing_pool.size != target_size:
                _global_fuzzing_pool.shutdown()
                _global_fuzzing_pool = None

        if _global_fuzzing_pool is None:
            _global_fuzzing_pool = BatchWorkerPool(size=target_size, config=sandbox_cfg, session_id="global_pool")
        return _global_fuzzing_pool

def shutdown_fuzzing_pool():
    global _global_fuzzing_pool
    with _global_fuzzing_pool_lock:
        if _global_fuzzing_pool is not None:
            # Wait up to 5s for in-flight submits to complete
            start = time.time()
            while time.time() - start < 5.0:
                if _global_fuzzing_pool._available_workers.qsize() == len(_global_fuzzing_pool._workers):
                    break
                time.sleep(0.05)
            _global_fuzzing_pool.shutdown()
            _global_fuzzing_pool = None

import atexit
atexit.register(shutdown_fuzzing_pool)
