---
interfaces: "adds two new top-level dataclasses Bounty and Target (each with to_dict/from_dict/validate) to the EXISTING module ngv2/contracts.py in the external NobleGreedv2 repo via the R-ANCHOR additive pattern (anchored on the existing top-level helper _is_nonempty_str); no existing symbol's behavior changes"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: data_model
---

# Title

ngv2/contracts.py — add the `Bounty` and `Target` sourcing/acquisition dataclasses (R-ANCHOR additive on the existing `_is_nonempty_str` helper)

# Scope

EDIT the EXISTING module `ngv2/contracts.py` in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is an ADDITIVE edit: add TWO brand-new top-level dataclasses, `Bounty` and `Target`, next to the existing `Finding`/`PoC`/`LiveTestReport`. NO existing symbol changes behavior; the only edit is the insertion of the two new classes.

Because a `kind:'symbol'` patch entry can ONLY replace an EXISTING top-level symbol, you MUST use the R-ANCHOR additive pattern: pick an EXISTING top-level symbol as the ANCHOR, reproduce its CURRENT source VERBATIM in the patch `code`, and carry the two NEW classes as EXTRA top-level nodes in the SAME `code` block. The harness inserts the extras immediately before the anchor and preserves every other byte of the file.

ANCHOR ON the existing top-level function `_is_nonempty_str` (it is a 1-part top-level name — required for R-ANCHOR extras). Its CURRENT verbatim source (copy EXACTLY from the read-only staged target `{WORK_DIR}/inbox/targets/ngv2/contracts.py`) is:

```
def _is_nonempty_str(value: object) -> bool:
    """Return True iff ``value`` is a non-empty ``str``."""
    return isinstance(value, str) and value != ''
```

The `Bounty` and `Target` classes use `dataclass`, `field`, `fields` and `_is_nonempty_str`, all of which already exist at module top level in `ngv2/contracts.py` (`from dataclasses import dataclass, field, fields`). Do NOT add any new import.

EMIT exactly ONE `__JANUSMASK_PATCHES__` list with ONE entry: kind `'symbol'`, name `'_is_nonempty_str'`, whose `code` reproduces `_is_nonempty_str` VERBATIM AND THEN defines `Bounty` and `Target` as extra top-level nodes. Do NOT emit a whole-file manifest, do NOT touch any other symbol, do NOT add imports.

# Non-Goals

INTEGRATION is out of scope — this leaf adds two pure stdlib dataclasses and is verified by its committed unit oracle alone; do NOT wire them into any pipeline, gate, loader, or scanner, and author NO test (the oracle is pre-committed). Do NOT modify `Finding`, `PoC`, `LiveTestReport`, `SEVERITIES`, `VERDICTS`, `_is_nonempty_str`'s behavior, the module docstring, or any import. No new file. No network, no I/O, no module-level side effects.

# Inputs

The authoritative contract is the PRE-COMMITTED RED oracle `tests/test_contracts_bounty_target_wired.py` (committed on NGv2 master at `f993242`). It imports `Bounty`/`Target` from the live `ngv2.contracts` module and pins the exact field order, defaults, `to_dict`/`from_dict` round-trip, and `validate()` invariants. READ it as the source of truth and make it GREEN.

The EXACT validated dataclass source to add as the two extra nodes (proven 13/13 GREEN against this oracle — embed VERBATIM, do NOT alter field names, order, defaults, or validate rules):

```
@dataclass
class Bounty:
    platform: str
    repo_url: str
    package: str
    cwe: str
    advisory_id: str
    tier: str
    observed_payout: int = 0
    max_paid: int = 0
    submissions: int = 0
    eligible: bool = False
    fp_risk: float = 0.0
    discovered_at: str = ''

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> 'Bounty':
        return cls(**{f.name: d[f.name] for f in fields(cls) if f.name in d})

    def validate(self) -> None:
        for name in ('platform', 'repo_url', 'package', 'cwe'):
            if not _is_nonempty_str(getattr(self, name)):
                raise ValueError(f'{name} must be a non-empty str')
        if self.observed_payout < 0:
            raise ValueError('observed_payout must be >= 0')
        if self.max_paid < 0:
            raise ValueError('max_paid must be >= 0')
        if self.submissions < 0:
            raise ValueError('submissions must be >= 0')
        if not (0.0 <= self.fp_risk <= 1.0):
            raise ValueError('fp_risk must be in [0.0, 1.0]')

@dataclass
class Target:
    repo_url: str
    repo_root: str
    pinned_commit: str
    language: str
    loc: int = 0
    cloned_at: str = ''

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict) -> 'Target':
        return cls(**{f.name: d[f.name] for f in fields(cls) if f.name in d})

    def validate(self) -> None:
        for name in ('repo_url', 'repo_root', 'pinned_commit', 'language'):
            if not _is_nonempty_str(getattr(self, name)):
                raise ValueError(f'{name} must be a non-empty str')
        if self.loc < 0:
            raise ValueError('loc must be >= 0')
```

# Required plan shape

Emit EXACTLY ONE impl task (do NOT decompose):
- meta_task_type: data_model
- files_touched: ["ngv2/contracts.py"] (this file ONLY)
- partial_edit semantics: ONE `__JANUSMASK_PATCHES__` symbol entry anchored on `_is_nonempty_str` with `Bounty`/`Target` as extra nodes (R-ANCHOR additive). NOT a whole-file rewrite.
- verification_command: `python -m pytest tests/test_contracts_bounty_target_wired.py tests/test_contracts.py -q`
  (ANTI-SEESAW union: `tests/test_contracts.py` pins the pre-existing Finding/PoC/LiveTestReport contract — both files MUST stay green. The `*_wired` oracle also satisfies the planner's wiring-oracle gate.)
- spec_author: null — the oracle is pre-committed at NGv2 `f993242`; author NO test.
- non_goals MUST contain the literal word `integration`.
- test_spec MUST carry >=2 regression_tests reflecting the field-set and validate edge cases below.

# Deliverables

`ngv2/contracts.py` with `Bounty` and `Target` added as top-level dataclasses (every other byte preserved), GREEN under `python -m pytest tests/test_contracts_bounty_target_wired.py tests/test_contracts.py -q`. Edge cases the oracle pins: exact field order (`Bounty` = platform,repo_url,package,cwe,advisory_id,tier,observed_payout,max_paid,submissions,eligible,fp_risk,discovered_at; `Target` = repo_url,repo_root,pinned_commit,language,loc,cloned_at); `validate()` rejects empty required strings, negative numerics, and `fp_risk` outside [0.0,1.0]; `to_dict`/`from_dict` round-trip.
