ALLOW = "allow"
DENY = "deny"
DECISIONS = frozenset({ALLOW, DENY})

def original(decision: str) -> str:
    token = (decision or "").strip().lower()
    if token not in DECISIONS:
        raise ValueError(
            f"unknown decision {decision!r}; expected one of {sorted(DECISIONS)}"
        )
    return token

def mine(decision: str) -> str:
    token = (decision or "").strip().lower()
    if token not in {"allow", "deny"}:
        raise ValueError(
            f"unknown decision {decision!r}; expected one of ['allow', 'deny']"
        )
    return token

import traceback
for val in ["allow", " deny ", "BLOCK", "", None, 123]:
    try:
        r1 = original(val)
    except Exception as e:
        r1 = str(e)
    try:
        r2 = mine(val)
    except Exception as e:
        r2 = str(e)
    if r1 != r2:
        print(f"Mismatch for {val}: {r1!r} != {r2!r}")
print("Done")
