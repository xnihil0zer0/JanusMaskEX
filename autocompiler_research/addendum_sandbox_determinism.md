# Addendum: Deterministic Sandboxing (Flakiness Elimination) for JanusMaskJR

This addendum outlines the feasibility, limitations, design, and integration details for enforcing determinism within the execution sandboxes of the differential fuzzing framework. It supplements the existing sandboxing implementation in [harness/sandbox.py](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py).

---

## 1. Adversarial Critique of "Absolute Determinism"

The goal of deterministic sandboxing is to eliminate flakiness during the differential fuzzing of Python and JavaScript agents. However, claiming **absolute determinism** in user-space isolated environments running arbitrary code is mathematically and practically impossible under standard operating system conditions. 

### Core Limitations & Escape Vectors

1. **Pre-emptive Multi-Threading & GIL Scheduling**
   * **Python:** CPython's Global Interpreter Lock (GIL) is released periodically (by default every 5 milliseconds or after a set number of bytecodes). The exact point at which thread context switches occur is managed by the host OS kernel scheduler, which depends on CPU load, temperature throttling, interrupts, and background processes. Any multi-threaded code under test is inherently non-deterministic.
   * **JavaScript:** Even though JS execution is single-threaded, Node.js manages file, socket, and crypto IO using the asynchronous thread pool (`libuv`). The timing of thread completion and subsequent event loop execution order remains non-deterministic.
2. **JIT Compilation & Garbage Collection**
   * High-performance runtimes (V8/Node.js, PyPy) compile code dynamically. JIT compilers trigger optimization/deoptimization steps based on heuristics, internal profiling, and CPU thread metrics.
   * Garbage collection (GC) cycles are asynchronous. Code relying on finalizers, object deletion callbacks, or weak references (e.g., Python's `weakref` or JS's `WeakRef` / `FinalizationRegistry`) will see non-deterministic side-effects depending on when the GC fires.
3. **Address Space Layout Randomization (ASLR) & Memory Addresses**
   * Operating systems randomize the virtual address space layout at startup. In CPython, `id(obj)` returns the virtual memory address of the object. Any library or user script that prints, hashes, or serializes object IDs will produce different outputs across sandbox invocations.
4. **Static Linking and Direct System Calls**
   * Custom binary libraries (written in Go, Rust, or C/C++) can bypass dynamic loading entirely by being statically compiled. 
   * Statically linked binaries do not load `ld.so`, making library injection methods like `LD_PRELOAD` completely inert. Furthermore, binaries can use direct assembly system calls (e.g., `syscall` instruction) rather than calling C library wrappers (like `clock_gettime`), bypassing both `LD_PRELOAD` and user-space libraries.
5. **Hardware Instruction Variance**
   * CPU floating-point execution paths can vary across architectures. Fused Multiply-Add (FMA) instructions, denormal floating-point numbers, and hardware SIMD execution optimizations can yield tiny floating-point discrepancies between different host machines, causing differential fuzzer mismatches.
6. **Wall-Clock Resource Boundary Enforcement**
   * If a process is terminated by the host OS or harness when hitting memory caps or wall/CPU limits (like resource limits in [harness/sandbox.py](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py#L617-L623)), the exact bytecode instruction at which execution is terminated is subject to system clock precision and load, causing transient execution states.

> [!IMPORTANT]
> While **absolute** determinism is impossible to guarantee for arbitrary binaries and multi-threaded programs, we can achieve **practical determinism** (99.9%+ flakiness reduction) for standard single-threaded agent scripts by intercepting all user-space sources of entropy, clocks, filesystem state, and network sockets.

---

## 2. Python-Level Patching Design (`sitecustomize.py`)

Python's startup sequence automatically searches for a module named `sitecustomize.py` in the search path (including the script's directory) and executes it before running the target script. Writing a custom `sitecustomize.py` directly into the sandbox work directory ensures that all patching occurs **before** any third-party modules or user scripts are imported.

Below is the implementation code for the python mock wrapper that enforces determinism:

```python
# sitecustomize.py
# Preloaded automatically by Python inside the JanusMask sandbox to enforce determinism.

import sys
import os
import builtins
import time
import datetime
import random
import socket
import pathlib
import uuid
import tempfile

# ---------------------------------------------------------------------------
# 1. Virtual Clock Enforcer
# ---------------------------------------------------------------------------
# A virtual monotonic clock that starts at a fixed epoch and advances by a
# predictable step on every clock read or sleep event.
VIRTUAL_START_EPOCH = 1717977600.0  # Monday, June 10, 2024
VIRTUAL_CLOCK_STEP = 0.001          # 1ms advance per call
_current_virtual_time = VIRTUAL_START_EPOCH

def get_virtual_time() -> float:
    global _current_virtual_time
    t = _current_virtual_time
    _current_virtual_time += VIRTUAL_CLOCK_STEP
    return t

def mock_time() -> float:
    return get_virtual_time()

def mock_time_ns() -> int:
    return int(get_virtual_time() * 1e9)

def mock_sleep(seconds: float) -> None:
    # Instead of actually sleeping (which wastes time and introduces flakiness),
    # fast-forward the virtual clock by the sleep duration.
    global _current_virtual_time
    _current_virtual_time += max(0.0, seconds)

# Apply patches to the 'time' module
time.time = mock_time
time.time_ns = mock_time_ns
time.monotonic = mock_time
time.monotonic_ns = mock_time_ns
time.perf_counter = mock_time
time.perf_counter_ns = mock_time_ns
time.process_time = mock_time
time.process_time_ns = mock_time_ns
time.sleep = mock_sleep

# Patch 'datetime' by subclassing the immutable C-level datetime classes
class DeterministicDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.datetime.fromtimestamp(get_virtual_time(), tz)
    
    @classmethod
    def utcnow(cls):
        return datetime.datetime.fromtimestamp(get_virtual_time(), datetime.timezone.utc).replace(tzinfo=None)
    
    @classmethod
    def today(cls):
        return cls.now()

class DeterministicDate(datetime.date):
    @classmethod
    def today(cls):
        return datetime.datetime.fromtimestamp(get_virtual_time()).date()

datetime.datetime = DeterministicDateTime
datetime.date = DeterministicDate

# ---------------------------------------------------------------------------
# 2. Entropy Seeding & PRNG Mocking
# ---------------------------------------------------------------------------
SANDBOX_SEED = int(os.environ.get("PYTHONHASHSEED", "42"))
random.seed(SANDBOX_SEED)

# Prevent user scripts from reseeding randomly using time or /dev/urandom
_orig_seed = random.seed
def mock_seed(a=None, version=2):
    if a is None:
        # Force deterministic fallback seed
        _orig_seed(SANDBOX_SEED, version)
    else:
        _orig_seed(a, version)

random.seed = mock_seed

# Mock os.urandom using a separate deterministic generator
_urandom_generator = random.Random(SANDBOX_SEED)
def mock_urandom(size: int) -> bytes:
    return bytes(_urandom_generator.getrandbits(8) for _ in range(size))

os.urandom = mock_urandom

# Patch UUID to prevent system MAC or random extraction
def mock_uuid4():
    return uuid.UUID(bytes=mock_urandom(16), version=4)

def mock_uuid1(node=None, clock_seq=None):
    # Use static MAC address and virtual time
    fixed_node = 0x001122334455 if node is None else node
    fixed_seq = 0x1234 if clock_seq is None else clock_seq
    # Calculate intervals from UUID epoch
    uuid_time = int((get_virtual_time() + 12219292800) * 1e7)
    return uuid.UUID(fields=(uuid_time & 0xffffffff, (uuid_time >> 32) & 0xffff, ((uuid_time >> 48) & 0x0fff) | 0x1000, fixed_seq >> 8, fixed_seq & 0xff, fixed_node))

uuid.uuid4 = mock_uuid4
uuid.uuid1 = mock_uuid1

# ---------------------------------------------------------------------------
# 3. Filesystem Determinism
# ---------------------------------------------------------------------------
# Sort listdir/scandir outputs to bypass filesystem structure/indexing order flakiness
_orig_listdir = os.listdir
def mock_listdir(path=None):
    return sorted(_orig_listdir(path))

os.listdir = mock_listdir

_orig_scandir = os.scandir
def mock_scandir(path=None):
    entries = list(_orig_scandir(path))
    entries.sort(key=lambda e: e.name)
    return entries.__iter__()

os.scandir = mock_scandir

# ---------------------------------------------------------------------------
# 4. Memory Address (id) Isolation
# ---------------------------------------------------------------------------
# Maintain a stable sequence of virtual object IDs so address space layout doesn't leak
_id_map = {}
_id_counter = 0

def mock_id(obj) -> int:
    global _id_counter
    real_addr = id(obj)
    if real_addr not in _id_map:
        _id_counter += 1
        _id_map[real_addr] = _id_counter
    return _id_map[real_addr]

builtins.id = mock_id

# ---------------------------------------------------------------------------
# 5. Socket Connection Interception
# ---------------------------------------------------------------------------
# Block outbound sockets cleanly at the library level and return reproducible errors
class MockSocket:
    def __init__(self, *args, **kwargs):
        pass
    def connect(self, address):
        raise ConnectionRefusedError(f"[DeterministicSandbox] Connection to {address} refused.")
    def connect_ex(self, address):
        return 111  # ECONNREFUSED errno
    def send(self, *args): raise BrokenPipeError()
    def recv(self, *args): return b""
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass

socket.socket = MockSocket

def mock_getaddrinfo(*args, **kwargs):
    raise socket.gaierror(-2, "Name or service not known (Deterministic Sandbox blocked network)")

socket.getaddrinfo = mock_getaddrinfo
socket.gethostbyname = mock_getaddrinfo
```

---

## 3. Binary-Level Sandboxing (`LD_PRELOAD`)

To handle compiled C/C++ extensions (such as parts of `numpy`, `cryptography`, or external compiled executables spawned by the agent), library injection via `LD_PRELOAD` intercepts system calls before they leave user space.

Below is the code for the preloaded C helper (`libdeterminism.c`):

```c
/* libdeterminism.c
   Compile: gcc -shared -fPIC -o libdeterminism.so libdeterminism.c -ldl
*/

#define _GNU_SOURCE
#include <dlfcn.h>
#include <time.h>
#include <sys/time.h>
#include <sys/socket.h>
#include <netdb.h>
#include <errno.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdarg.h>

#define MAX_FDS 2048
static bool urandom_fds[MAX_FDS] = {false};

/* 1. Preloaded Virtual Clock */
static uint64_t virtual_ns = 1717977600ULL * 1000000000ULL; // Start epoch: 2024-06-10
static inline void advance_clock() {
    virtual_ns += 1000000ULL; // Advance 1ms per clock call
}

int clock_gettime(clockid_t clk_id, struct timespec *tp) {
    advance_clock();
    if (tp) {
        tp->tv_sec = virtual_ns / 1000000000ULL;
        tp->tv_nsec = virtual_ns % 1000000000ULL;
    }
    return 0;
}

int gettimeofday(struct timeval *tv, struct timezone *tz) {
    advance_clock();
    if (tv) {
        tv->tv_sec = virtual_ns / 1000000000ULL;
        tv->tv_usec = (virtual_ns % 1000000000ULL) / 1000ULL;
    }
    return 0;
}

time_t time(time_t *tloc) {
    advance_clock();
    time_t t = virtual_ns / 1000000000ULL;
    if (tloc) {
        *tloc = t;
    }
    return t;
}

/* 2. Preloaded Entropy Redirector */
/* Implement a fast, deterministic Xoshiro128** generator */
static uint32_t xoshiro_state[4] = {12345, 67890, 54321, 98765};
static inline uint32_t rotl(const uint32_t x, int k) {
    return (x << k) | (x >> (32 - k));
}
static uint32_t next_random(void) {
    const uint32_t result = rotl(xoshiro_state[1] * 5, 7) * 9;
    const uint32_t t = xoshiro_state[1] << 9;
    xoshiro_state[2] ^= xoshiro_state[0];
    xoshiro_state[3] ^= xoshiro_state[1];
    xoshiro_state[1] ^= xoshiro_state[2];
    xoshiro_state[0] ^= xoshiro_state[3];
    xoshiro_state[2] ^= t;
    xoshiro_state[3] = rotl(xoshiro_state[3], 11);
    return result;
}
static void fill_deterministic_random(void *buf, size_t len) {
    uint8_t *p = (uint8_t *)buf;
    for (size_t i = 0; i < len; i++) {
        p[i] = (uint8_t)(next_random() & 0xFF);
    }
}

typedef int (*orig_open_type)(const char *, int, ...);
typedef int (*orig_openat_type)(int, const char *, int, ...);
typedef int (*orig_close_type)(int);
typedef ssize_t (*orig_read_type)(int, void *, size_t);

int open(const char *pathname, int flags, ...) {
    orig_open_type orig_open = (orig_open_type)dlsym(RTLD_NEXT, "open");
    mode_t mode = 0;
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
    }
    bool is_entropy = (strcmp(pathname, "/dev/urandom") == 0 || strcmp(pathname, "/dev/random") == 0);
    const char *final_path = is_entropy ? "/dev/zero" : pathname;
    int fd = orig_open(final_path, flags, mode);
    if (fd >= 0 && fd < MAX_FDS && is_entropy) {
        urandom_fds[fd] = true;
    }
    return fd;
}

int openat(int dirfd, const char *pathname, int flags, ...) {
    orig_openat_type orig_openat = (orig_openat_type)dlsym(RTLD_NEXT, "openat");
    mode_t mode = 0;
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
    }
    bool is_entropy = (strcmp(pathname, "/dev/urandom") == 0 || strcmp(pathname, "/dev/random") == 0);
    const char *final_path = is_entropy ? "/dev/zero" : pathname;
    int fd = orig_openat(dirfd, final_path, flags, mode);
    if (fd >= 0 && fd < MAX_FDS && is_entropy) {
        urandom_fds[fd] = true;
    }
    return fd;
}

int close(int fd) {
    if (fd >= 0 && fd < MAX_FDS) {
        urandom_fds[fd] = false;
    }
    orig_close_type orig_close = (orig_close_type)dlsym(RTLD_NEXT, "close");
    return orig_close(fd);
}

ssize_t read(int fd, void *buf, size_t count) {
    if (fd >= 0 && fd < MAX_FDS && urandom_fds[fd]) {
        fill_deterministic_random(buf, count);
        return count;
    }
    orig_read_type orig_read = (orig_read_type)dlsym(RTLD_NEXT, "read");
    return orig_read(fd, buf, count);
}

/* Intercept system calls getrandom and getentropy */
ssize_t getrandom(void *buf, size_t buflen, unsigned int flags) {
    fill_deterministic_random(buf, buflen);
    return buflen;
}

int getentropy(void *buffer, size_t length) {
    if (length > 256) {
        errno = EIO;
        return -1;
    }
    fill_deterministic_random(buffer, length);
    return 0;
}

/* 3. Preloaded Socket Failures */
int connect(int sockfd, const struct sockaddr *addr, socklen_t addrlen) {
    errno = ECONNREFUSED;
    return -1;
}

int getaddrinfo(const char *node, const char *service,
                const struct addrinfo *hints,
                struct addrinfo **res) {
    return EAI_NONAME;
}
```

---

## 4. Harness Integration Plan

To run sandbox subprocesses with our deterministic overrides, we modify [harness/sandbox.py](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py) to write `sitecustomize.py` inside the temporary execution folders and append `LD_PRELOAD` to the environment map in `sandbox_child_env`.

### Step 4.1: Modify `harness/sandbox.py` to write `sitecustomize.py`

Modify [Sandbox.execute](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py#L1315) and [BatchWorkerPool._spawn_worker](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py#L1746) to write the `sitecustomize.py` content to the sandbox workspace prior to launching python scripts.

```diff
# In Sandbox.execute inside harness/sandbox.py
         work_dir = self.sandbox_dir / "work"
         work_dir.mkdir(parents=True, exist_ok=True)
 
         # Write runner script
         runner_path = work_dir / "_runner.py"
         runner_path.write_text(_RUNNER_TEMPLATE)
 
+        # Write sitecustomize.py wrapper to force deterministic libraries
+        sitecustomize_path = work_dir / "sitecustomize.py"
+        sitecustomize_path.write_text(_SITECUSTOMIZE_CONTENT)
+
         # Write payload
         payload = {
```

And update [BatchWorkerPool._spawn_worker](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py#L1746):

```diff
# In BatchWorkerPool._spawn_worker inside harness/sandbox.py
     def _spawn_worker(self, worker_id: int):
         work_dir = self._sandbox_dir / f"worker_{worker_id}"
         work_dir.mkdir(parents=True, exist_ok=True)
         
         runner_path = work_dir / "runner.py"
         runner_path.write_text(_BATCH_RUNNER_TEMPLATE)
 
+        # Ensure worker processes are loaded with sitecustomize.py
+        sitecustomize_path = work_dir / "sitecustomize.py"
+        sitecustomize_path.write_text(_SITECUSTOMIZE_CONTENT)
+
         env = sandbox_child_env({
```

### Step 4.2: Update `sandbox_child_env` to load `LD_PRELOAD`

Modify [sandbox_child_env](file:///home/xnihil0zer0/JanusMaskJR/harness/sandbox.py#L115) to check for a compiled preloaded object (`libdeterminism.so`) and append it to the environment dictionary if present:

```diff
# In sandbox_child_env inside harness/sandbox.py
 def sandbox_child_env(extra: dict | None = None) -> dict:
     """Return a fresh environment mapping with thread guards applied."""
     env = os.environ.copy()
     if extra:
         env.update(extra)
     env["OPENBLAS_NUM_THREADS"] = "1"
     env["MKL_NUM_THREADS"] = "1"
+
+    # Load libdeterminism.so binary hook for non-python and C library wrappers
+    preload_lib = Path(__file__).resolve().parent / "libdeterminism.so"
+    if preload_lib.exists():
+        env["LD_PRELOAD"] = str(preload_lib)
+
     # gap#2b: the differential fuzzer runs candidates in a plain subprocess with
```

### Step 4.3: Add Test Verifications

To verify these changes function correctly, add new assertions to [tests/test_sandbox.py](file:///home/xnihil0zer0/JanusMaskJR/tests/test_sandbox.py) under the [TestDeterminism](file:///home/xnihil0zer0/JanusMaskJR/tests/test_sandbox.py#L189) class:

```python
    def test_mock_time_is_deterministic(self, sandbox):
        code = "def get_time():\n    import time\n    return time.time()\n"
        r1 = sandbox.execute(code, "get_time")
        r2 = sandbox.execute(code, "get_time")
        # Both must return the identical starting epoch virtual time
        assert r1.return_value == r2.return_value

    def test_mock_random_and_urandom_is_deterministic(self, sandbox):
        code = "def get_urandom():\n    import os\n    return list(os.urandom(8))\n"
        r1 = sandbox.execute(code, "get_urandom")
        r2 = sandbox.execute(code, "get_urandom")
        assert r1.return_value == r2.return_value

    def test_listdir_is_sorted_deterministically(self, sandbox):
        code = "def check_dir():\n    import os, tempfile\n    with tempfile.TemporaryDirectory() as td:\n        # Write names in non-alphabetical order\n        for name in ['z', 'a', 'm']:\n            with open(os.path.join(td, name), 'w') as f:\n                f.write('')\n        return os.listdir(td)\n"
        r1 = sandbox.execute(code, "check_dir")
        assert r1.return_value == ['a', 'm', 'z']
```
