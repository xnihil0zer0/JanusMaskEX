from __future__ import annotations
import json
import sys
from harness.hooks._common import HookInputError

def read_input(stream=None) -> dict[str, Any]:
    """Read and parse the hook envelope from stdin (or provided stream)."""
    stream = stream if stream is not None else sys.stdin
    try:
        content = stream.read()
        return json.loads(content)
    except ValueError as e:
        raise HookInputError("malformed JSON envelope") from e
