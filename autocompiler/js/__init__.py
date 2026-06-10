"""JS/TS target beachhead for the autocompiler (Phase B).

Pure policy/codec modules only; the single real Node I/O lives in
``js_runner.js`` and is reached exclusively through the injected spawn seam
in ``js_sandbox`` (and, at runtime, the bwrap agent jail — never the seccomp
fuzz sandbox, which blocks execve/fork by design).
"""
