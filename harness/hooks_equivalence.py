"""Shadow-mode decision logger + equivalence primitives (HOOK-50).

Owned by Phase 5 of the hooks migration. Two responsibilities:

1. ``record_shadow_decision`` appends one JSON line per hook invocation
   to ``state/hooks/shadow/<session>.jsonl`` with the schema from
   sub-plan 06 §4.5:

       {ts, session_id, tool_name, args_hash, policy_decision, policy_reason}

2. ``maybe_record_shadow`` reads ``hooks.mode`` from ``harness/config.yaml``
   and emits a shadow row when the mode is ``shadow`` or ``enforce``;
   it is a no-op when the mode is ``off``. It is the call site used by
   the Claude / Gemini PreToolUse hooks during Phase 5 shadow/canary.

Fail-open is load-bearing: neither the config read nor the shadow
write is allowed to raise out of this module. Shadow telemetry must
never break the hook flow. Failures are surfaced on stderr only.

Interpretation note (post-HOOK-41): the Claude worker is already on
hook-authoritative mode. ``shadow`` mode here does not neutralise
enforcement — the hook still denies/allows per policy — it additionally
emits a decision record so the L2 equivalence comparator (HOOK-51) has
something to diff against the MCP-era audit log.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Any, Optional

_DEFAULT_SHADOW_DIR = "state/hooks/shadow/"
_ARGS_HASH_LEN = 16
_DEFAULT_CONFIG_REL = pathlib.Path("harness") / "config.yaml"


@dataclass
class _HooksConfigView:
    """Minimal view the shadow logger needs from the hooks config.

    Kept narrow on purpose so tests can supply a fake loader without
    pulling in the full ``harness.config_loader.HooksConfig`` validation
    rules (those are exercised by tests/hooks/unit/test_hooks_config.py).
    """

    mode: str
    shadow_dir: str


def now_iso() -> str:
    """UTC timestamp in the ledger convention (no micros, Z suffix)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def args_hash(tool_input: Optional[dict]) -> str:
    """Stable 16-hex-char sha256 prefix of ``tool_input``.

    Uses ``sort_keys=True`` so key-order rearrangement produces the same
    hash (sub-plan 06 §4.5 functional_requirements). ``default=str``
    keeps us robust to tuples, bytes, Path etc. in fuzz payloads.
    """
    serialised = json.dumps(tool_input or {}, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()[:_ARGS_HASH_LEN]


def _project_dir() -> pathlib.Path:
    env = os.environ.get("JANUSMASK_PROJECT_DIR") or os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return pathlib.Path(env)
    return pathlib.Path(__file__).resolve().parent.parent


def _session_or_fallback(session_id: Optional[str]) -> str:
    if session_id:
        return session_id
    return f"unknown-{os.getpid()}"


def _resolve_shadow_dir(
    shadow_dir: Optional[pathlib.Path | str],
) -> pathlib.Path:
    if shadow_dir is None:
        base = pathlib.Path(_DEFAULT_SHADOW_DIR)
    else:
        base = pathlib.Path(shadow_dir)
    if not base.is_absolute():
        base = _project_dir() / base
    return base


def shadow_path(
    session_id: Optional[str],
    shadow_dir: Optional[pathlib.Path | str] = None,
) -> pathlib.Path:
    """Return the shadow JSON-lines path for ``session_id``.

    When ``session_id`` is missing the path falls back to
    ``unknown-<pid>.jsonl`` so concurrent no-session hooks don't
    clobber each other.
    """
    base = _resolve_shadow_dir(shadow_dir)
    return base / f"{_session_or_fallback(session_id)}.jsonl"


def _ensure_parent(p: pathlib.Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)


def record_shadow_decision(
    session_id: Optional[str],
    tool_name: str,
    tool_input: Optional[dict],
    policy_decision: str,
    policy_reason: str = "",
    *,
    shadow_dir: Optional[pathlib.Path | str] = None,
) -> None:
    """Append one shadow-decision row; swallow all IO/serialisation errors.

    The six-field schema mirrors sub-plan 06 §4.5; the equivalence
    comparator (HOOK-51) treats ``(tool_name, args_hash, policy_decision)``
    as the diff key.
    """
    try:
        target = shadow_path(session_id, shadow_dir)
        _ensure_parent(target)
        row = {
            "ts": now_iso(),
            "session_id": _session_or_fallback(session_id),
            "tool_name": tool_name,
            "args_hash": args_hash(tool_input),
            "policy_decision": policy_decision,
            "policy_reason": policy_reason,
        }
        is_new = not target.exists()
        with target.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        if is_new:
            try:
                target.chmod(0o600)
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001 — fail-open by contract
        sys.stderr.write(
            f"[hooks_equivalence] shadow-write failed (session={session_id!r}): {exc}\n"
        )


def _decision_from_payload(payload: Optional[dict]) -> tuple[str, str]:
    payload = payload or {}
    decision = str(payload.get("decision") or "")
    reason = str(payload.get("reason") or "")
    return decision, reason


class _DefaultConfigLoader:
    """Default loader used when ``maybe_record_shadow`` isn't given one.

    Reads ``harness/config.yaml`` under ``JANUSMASK_PROJECT_DIR`` (or
    the repo root when that env is unset) and projects it into the
    ``_HooksConfigView`` shape. yaml is imported lazily so importing
    ``harness.hooks_equivalence`` during collect-only pytest runs
    stays cheap.
    """

    def read_hooks_config(
        self, path: Optional[pathlib.Path | str] = None
    ) -> _HooksConfigView:
        import yaml  # local to keep module import side-effect-free

        cfg_path = (
            pathlib.Path(path)
            if path is not None
            else _project_dir() / _DEFAULT_CONFIG_REL
        )
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        hooks_block = cfg.get("hooks") or {}
        return _HooksConfigView(
            mode=str(hooks_block.get("mode") or "off"),
            shadow_dir=str(hooks_block.get("shadow_dir") or _DEFAULT_SHADOW_DIR),
        )


_default_loader = _DefaultConfigLoader()


def maybe_record_shadow(
    session_id: Optional[str],
    tool_name: str,
    tool_input: Optional[dict],
    payload: dict,
    *,
    config_loader: object | None = None,
) -> None:
    """Emit a shadow row when ``hooks.mode != 'off'``; no-op otherwise.

    ``config_loader`` must expose ``read_hooks_config(path=None) ->
    _HooksConfigView``; the default uses ``_DefaultConfigLoader`` which
    reads ``harness/config.yaml``. Swallows every exception and writes
    a one-line stderr note so a misconfigured hook never takes the
    tool-call down with it.
    """
    try:
        loader = config_loader if config_loader is not None else _default_loader
        view = loader.read_hooks_config()
        # Fail-closed on unknown enums: anything other than shadow/enforce
        # is treated as off (sub-plan 06 §4.5 edge-case row 4).
        if str(view.mode) not in ("shadow", "enforce"):
            return
        decision, reason = _decision_from_payload(payload)
        record_shadow_decision(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            policy_decision=decision,
            policy_reason=reason,
            shadow_dir=view.shadow_dir,
        )
    except Exception as exc:  # noqa: BLE001 — fail-open by contract
        sys.stderr.write(
            f"[hooks_equivalence] maybe_record_shadow error "
            f"(session={session_id!r}): {exc}\n"
        )



# === Equivalence comparator (HOOK-51) ======================================


from collections import Counter
from dataclasses import field


_DEFAULT_AUDIT_SESSIONS_REL = pathlib.Path("state") / "sessions"
_DEFAULT_REPORT_DIR_REL = pathlib.Path("state") / "hooks"


def load_jsonl(path: "pathlib.Path | str") -> list[dict]:
    """Read a JSONL file into a list of dicts; skip malformed lines.

    Missing files return an empty list; this keeps the comparator
    resilient to sessions that never emitted any rows on one side.
    """
    p = pathlib.Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    except OSError as exc:
        sys.stderr.write(f"[hooks_equivalence] load_jsonl({p}) failed: {exc}\n")
    return out


def load_shadow_log(
    session_id: str,
    shadow_dir: "pathlib.Path | str | None" = None,
) -> list[dict]:
    """Load the shadow JSONL for ``session_id``."""
    return load_jsonl(shadow_path(session_id, shadow_dir))


def _audit_sessions_dir(audit_root: "pathlib.Path | str | None") -> pathlib.Path:
    if audit_root is None:
        return _project_dir() / _DEFAULT_AUDIT_SESSIONS_REL
    root = pathlib.Path(audit_root)
    return root / "sessions" if root.name != "sessions" else root


def load_mcp_audit(
    session_id: str,
    *,
    agent: "str | None" = None,
    audit_root: "pathlib.Path | str | None" = None,
) -> list[dict]:
    """Load MCP-era per-session ledger rows for ``session_id``.

    Matches ``state/sessions/{agent}_{session}.ledger.jsonl`` produced by
    harness.hooks._ledger.append_hook_event. When ``agent`` is omitted all
    matching files are concatenated in sorted-filename order so repeated
    runs produce deterministic report bodies.
    """
    sessions_dir = _audit_sessions_dir(audit_root)
    if not sessions_dir.exists():
        return []
    suffix = f"_{session_id}.ledger.jsonl"
    if agent:
        candidates = [sessions_dir / f"{agent}{suffix}"]
    else:
        candidates = sorted(sessions_dir.glob(f"*{suffix}"))
    rows: list[dict] = []
    for c in candidates:
        rows.extend(load_jsonl(c))
    return rows


def shadow_diff_key(row: dict) -> tuple[str, str, str]:
    """Project a shadow row into the ``(tool_name, args_hash, decision)`` triple.

    Missing fields degrade to empty strings so malformed rows still
    participate in the diff (and are visible as 3-tuples of empty keys).
    """
    return (
        str(row.get("tool_name") or ""),
        str(row.get("args_hash") or ""),
        str(row.get("policy_decision") or ""),
    )


_MCP_DENY_ALIASES = frozenset({"rate_limited", "invalid"})


def mcp_diff_key(row: dict) -> tuple[str, str, str]:
    """Project an MCP/hook ledger row into the shadow-style triple.

    Handles three independent schema drifts between the old MCP audit and
    the new shadow log:

    * ``tool`` (MCP) vs ``tool_name`` (shadow).
    * ``digest`` (MCP) vs ``args_hash`` (shadow) — if both are present,
      ``args_hash`` wins so hook-produced ledger rows (which carry the
      shadow-canonical hash) stay authoritative.
    * ``outcome`` (MCP) vs ``decision`` (shadow) — and ``rate_limited`` /
      ``invalid`` both collapse to ``deny`` because the Claude / Gemini
      hooks only speak the allow/deny vocabulary per _common.DECISIONS.
    """
    tool = str(row.get("tool") or row.get("tool_name") or "")
    ah = str(row.get("args_hash") or "") or str(row.get("digest") or "")
    dec = str(row.get("outcome") or row.get("decision") or "")
    if dec in _MCP_DENY_ALIASES:
        dec = "deny"
    return (tool, ah, dec)


@dataclass
class EquivReport:
    """Output of ``compare``; serialisable to JSON via ``to_dict``."""

    session_id: str
    match_rate: float
    divergences: list[dict]
    shadow_count: int
    mcp_count: int
    shadow_source: str = ""
    mcp_source: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "match_rate": self.match_rate,
            "divergences": [
                {
                    "source": d["source"],
                    "key": list(d["key"]),
                    "row": d["row"],
                }
                for d in self.divergences
            ],
            "shadow_count": self.shadow_count,
            "mcp_count": self.mcp_count,
            "shadow_source": self.shadow_source,
            "mcp_source": self.mcp_source,
            "generated_at": self.generated_at,
        }


def _multiset_diff(
    shadow_rows: list[dict],
    mcp_rows: list[dict],
    shadow_key,
    mcp_key,
) -> list[dict]:
    """Return the list of divergence entries, each tagged with source."""
    shadow_keyed = [(shadow_key(r), r) for r in shadow_rows]
    mcp_keyed = [(mcp_key(r), r) for r in mcp_rows]
    shadow_counter: Counter = Counter(k for k, _ in shadow_keyed)
    mcp_counter: Counter = Counter(k for k, _ in mcp_keyed)

    divergences: list[dict] = []

    # Shadow-side surplus: rows present in shadow but unmatched by MCP.
    for k, cnt in shadow_counter.items():
        surplus = cnt - mcp_counter.get(k, 0)
        if surplus > 0:
            matching_rows = [row for key, row in shadow_keyed if key == k][:surplus]
            for row in matching_rows:
                divergences.append({"source": "shadow", "key": k, "row": row})

    # MCP-side surplus: rows present in MCP but unmatched by shadow.
    for k, cnt in mcp_counter.items():
        surplus = cnt - shadow_counter.get(k, 0)
        if surplus > 0:
            matching_rows = [row for key, row in mcp_keyed if key == k][:surplus]
            for row in matching_rows:
                divergences.append({"source": "mcp", "key": k, "row": row})

    return divergences


def compare(
    shadow_rows: list[dict],
    mcp_rows: list[dict],
    *,
    shadow_key=shadow_diff_key,
    mcp_key=mcp_diff_key,
    session_id: str = "",
    shadow_source: str = "",
    mcp_source: str = "",
) -> EquivReport:
    """Multiset diff of two decision feeds on the 3-tuple key.

    ``match_rate`` is ``(total_events - divergences) / total_events`` where
    ``total_events = max(shadow_count, mcp_count)``. Empty feeds on both
    sides report a clean match rate of 1.0.
    """
    shadow_rows = list(shadow_rows)
    mcp_rows = list(mcp_rows)
    divergences = _multiset_diff(shadow_rows, mcp_rows, shadow_key, mcp_key)
    total = max(len(shadow_rows), len(mcp_rows))
    if total == 0:
        match_rate = 1.0
    else:
        match_rate = (total - len(divergences)) / total
        if match_rate < 0:
            match_rate = 0.0
    return EquivReport(
        session_id=session_id,
        match_rate=match_rate,
        divergences=divergences,
        shadow_count=len(shadow_rows),
        mcp_count=len(mcp_rows),
        shadow_source=shadow_source,
        mcp_source=mcp_source,
        generated_at=now_iso(),
    )


def _report_path(session_id: str, output_dir: "pathlib.Path | None") -> pathlib.Path:
    if output_dir is None:
        return _project_dir() / _DEFAULT_REPORT_DIR_REL / f"equiv_report_{session_id}.json"
    return pathlib.Path(output_dir) / f"equiv_report_{session_id}.json"


def emit_report(
    report: EquivReport,
    *,
    output_dir: "pathlib.Path | str | None" = None,
) -> pathlib.Path:
    """Write ``equiv_report_<session>.json`` and return the path."""
    out_dir_path = pathlib.Path(output_dir) if output_dir is not None else None
    target = _report_path(report.session_id, out_dir_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return target


def run_comparison(
    session_id: str,
    *,
    shadow_dir: "pathlib.Path | str | None" = None,
    audit_root: "pathlib.Path | str | None" = None,
    output_dir: "pathlib.Path | str | None" = None,
    agent: "str | None" = None,
) -> EquivReport:
    """Load shadow + MCP logs, diff them, emit the equiv report, return it."""
    shadow_rows = load_shadow_log(session_id, shadow_dir=shadow_dir)
    mcp_rows = load_mcp_audit(session_id, agent=agent, audit_root=audit_root)
    report = compare(
        shadow_rows,
        mcp_rows,
        session_id=session_id,
        shadow_source=str(shadow_path(session_id, shadow_dir)),
        mcp_source=str(_audit_sessions_dir(audit_root)),
    )
    emit_report(report, output_dir=output_dir)
    return report


# === Shadow->enforce diff gate (HOOK-52) ====================================


_DEFAULT_MIN_CLEAN_RUNS = 3


@dataclass
class DiffGateResult:
    """Outcome of the shadow→enforce diff gate.

    ``passed`` is True only when the most recent ``required_clean_runs``
    equivalence reports all had ``match_rate == 1.0`` and no divergences.
    ``clean_run_count`` is the length of the consecutive clean streak
    counted from the most-recent report backwards (it stops at the first
    divergent or malformed report). ``considered_reports`` is every file
    the scan actually opened, ordered from most-recent to oldest.
    """

    passed: bool
    clean_run_count: int
    required_clean_runs: int
    reason: str = ""
    considered_reports: list[str] = field(default_factory=list)


def list_equiv_reports(
    reports_dir: "pathlib.Path | str | None" = None,
) -> list[pathlib.Path]:
    """Return ``equiv_report_*.json`` files sorted by mtime (newest first).

    Missing directories return an empty list so the gate can decide for
    itself whether that constitutes a fail (it does: zero reports never
    satisfies a positive ``min_clean_runs``).
    """
    base = (
        pathlib.Path(reports_dir)
        if reports_dir is not None
        else _project_dir() / _DEFAULT_REPORT_DIR_REL
    )
    if not base.exists() or not base.is_dir():
        return []
    return sorted(
        base.glob("equiv_report_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def _load_report(path: pathlib.Path) -> dict | None:
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        obj = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _is_clean_report(report: dict) -> bool:
    try:
        match_rate = float(report.get("match_rate"))
    except (TypeError, ValueError):
        return False
    if match_rate != 1.0:
        return False
    divergences = report.get("divergences")
    if divergences:
        return False
    return True


class _DefaultMinCleanRunsLoader:
    """Reads ``hooks.shadow_min_clean_runs`` from ``harness/config.yaml``.

    Kept narrow like ``_DefaultConfigLoader`` so tests can substitute a
    fake loader. Fail-open on every failure path: falls back to the
    hard-coded default. The gate refuses to mask a broken config with a
    *lower* threshold, so silent recovery here is safe.
    """

    def read_hooks_min_clean_runs(self) -> int:
        import yaml  # local to keep import side-effect-free

        cfg_path = _project_dir() / _DEFAULT_CONFIG_REL
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        hooks_block = cfg.get("hooks") or {}
        value = hooks_block.get("shadow_min_clean_runs", _DEFAULT_MIN_CLEAN_RUNS)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"hooks.shadow_min_clean_runs must be int, got {type(value).__name__}"
            )
        if value < 1:
            raise ValueError("hooks.shadow_min_clean_runs must be >= 1")
        return value


_default_min_clean_runs_loader = _DefaultMinCleanRunsLoader()


def _resolve_min_clean_runs(config_loader: object | None) -> int:
    loader = (
        config_loader
        if config_loader is not None
        else _default_min_clean_runs_loader
    )
    try:
        value = loader.read_hooks_min_clean_runs()
    except Exception as exc:  # noqa: BLE001 — fail-open to the hard default
        sys.stderr.write(
            f"[hooks_equivalence] shadow_min_clean_runs read failed, "
            f"using default {_DEFAULT_MIN_CLEAN_RUNS}: {exc}\n"
        )
        return _DEFAULT_MIN_CLEAN_RUNS
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        sys.stderr.write(
            f"[hooks_equivalence] shadow_min_clean_runs loader returned "
            f"non-positive-int {value!r}; using default {_DEFAULT_MIN_CLEAN_RUNS}\n"
        )
        return _DEFAULT_MIN_CLEAN_RUNS
    return value


def check_diff_gate(
    *,
    min_clean_runs: int | None = None,
    reports_dir: "pathlib.Path | str | None" = None,
    config_loader: object | None = None,
) -> DiffGateResult:
    """Decide whether the shadow→enforce canary flip is permitted.

    Walks ``state/hooks/equiv_report_*.json`` (or ``reports_dir`` when
    overridden) from most-recent to oldest and counts consecutive clean
    reports. Returns ``passed=True`` as soon as the count reaches
    ``min_clean_runs``. The first divergent or malformed report ends the
    scan with ``passed=False`` — there is no "skip" — a single bad run
    resets the streak to whatever was counted before it.

    ``min_clean_runs`` must be a positive int. Passing 0 or negative is
    a programming error: the P5 shadow phase is the whole point of the
    gate, so a zero floor is rejected loudly rather than silently.
    """
    if min_clean_runs is None:
        resolved = _resolve_min_clean_runs(config_loader)
    else:
        if isinstance(min_clean_runs, bool) or not isinstance(min_clean_runs, int):
            raise ValueError(
                f"min_clean_runs must be a positive int, got "
                f"{type(min_clean_runs).__name__}"
            )
        if min_clean_runs < 1:
            raise ValueError(
                "min_clean_runs must be >= 1; a zero floor defeats the shadow phase."
            )
        resolved = min_clean_runs

    reports = list_equiv_reports(reports_dir)
    considered: list[str] = []
    clean_count = 0

    for path in reports:
        considered.append(str(path))
        report = _load_report(path)
        if report is None:
            return DiffGateResult(
                passed=False,
                clean_run_count=clean_count,
                required_clean_runs=resolved,
                reason=(
                    f"Report {path.name} is unreadable or malformed; "
                    f"streak broken at {clean_count} clean run(s)."
                ),
                considered_reports=considered,
            )
        if _is_clean_report(report):
            clean_count += 1
            if clean_count >= resolved:
                return DiffGateResult(
                    passed=True,
                    clean_run_count=clean_count,
                    required_clean_runs=resolved,
                    reason="",
                    considered_reports=considered,
                )
        else:
            match_rate = report.get("match_rate")
            divergences = report.get("divergences") or []
            return DiffGateResult(
                passed=False,
                clean_run_count=clean_count,
                required_clean_runs=resolved,
                reason=(
                    f"Report {path.name} diverged "
                    f"(match_rate={match_rate}, divergences={len(divergences)}); "
                    f"streak broken at {clean_count} clean run(s)."
                ),
                considered_reports=considered,
            )

    return DiffGateResult(
        passed=False,
        clean_run_count=clean_count,
        required_clean_runs=resolved,
        reason=(
            f"Only {clean_count} clean run(s) found; {resolved} required."
        ),
        considered_reports=considered,
    )


# === Per-verb canary enforce (HOOK-53) ======================================


# Master plan §5.3 canonical order: lowest-risk verb first, hottest-
# coupling (submit_code) last. Tuple, not list — consumers must not
# mutate it. The order itself is load-bearing: sub-plan 04 risk #1 is
# submit_code enforcement, which is why it flips last.
CANARY_ORDER: tuple[str, ...] = (
    "request_clarification",
    "report_error",
    "submit_reconciliation_response",
    "submit_plan_draft",
    "submit_code",
)


def _validate_enforce_verbs(enforce_verbs: list[str]) -> list[str]:
    if not isinstance(enforce_verbs, list):
        raise TypeError(
            f"enforce_verbs must be a list, got {type(enforce_verbs).__name__}"
        )
    return enforce_verbs


def is_verb_enforced(verb: str, enforce_verbs: list[str]) -> bool:
    """Return True iff ``verb`` is in the authoritative-hook allowlist."""
    if not isinstance(verb, str):
        raise TypeError(f"verb must be str, got {type(verb).__name__}")
    _validate_enforce_verbs(enforce_verbs)
    return verb in enforce_verbs


def canary_next_verb(enforce_verbs: list[str]) -> Optional[str]:
    """Return the next verb to enforce, or None when the canary is complete.

    Ordering follows ``CANARY_ORDER``; already-enforced verbs are skipped
    but the sequence is never reordered. Unrecognised entries in
    ``enforce_verbs`` (theoretical — config validation rejects them) are
    simply ignored: the next known verb still flips.
    """
    _validate_enforce_verbs(enforce_verbs)
    already = {v for v in enforce_verbs if isinstance(v, str)}
    for v in CANARY_ORDER:
        if v not in already:
            return v
    return None


@dataclass
class CanaryFlipDecision:
    """Planner output: what the next canary flip would be, and can it happen.

    ``ready`` means the diff gate is green *and* a verb remains to flip.
    ``human_gate_required`` is True whenever a flip is identified — per
    sub-plan 06 §5 item 4 every shadow→enforce trust-step is a human
    decision, not just the first.
    """

    verb: Optional[str]
    ready: bool
    reason: str
    diff_gate: "DiffGateResult"
    human_gate_required: bool
    current_enforce_verbs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verb": self.verb,
            "ready": self.ready,
            "reason": self.reason,
            "human_gate_required": self.human_gate_required,
            "current_enforce_verbs": list(self.current_enforce_verbs),
            "diff_gate": {
                "passed": self.diff_gate.passed,
                "clean_run_count": self.diff_gate.clean_run_count,
                "required_clean_runs": self.diff_gate.required_clean_runs,
                "reason": self.diff_gate.reason,
                "considered_reports": list(self.diff_gate.considered_reports),
            },
        }


class _DefaultEnforceVerbsLoader:
    """Reads ``hooks.enforce_verbs`` from ``harness/config.yaml``.

    Same fail-open contract as the other default loaders: a broken config
    returns an empty list so the planner errs on the conservative side.
    """

    def read_hooks_enforce_verbs(self) -> list[str]:
        import yaml

        cfg_path = _project_dir() / _DEFAULT_CONFIG_REL
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        hooks_block = cfg.get("hooks") or {}
        value = hooks_block.get("enforce_verbs") or []
        if not isinstance(value, list):
            raise ValueError("hooks.enforce_verbs must be a list")
        return [str(v) for v in value if isinstance(v, str)]


_default_enforce_verbs_loader = _DefaultEnforceVerbsLoader()


def _resolve_enforce_verbs(
    enforce_verbs: list[str] | None,
    config_loader: object | None,
) -> list[str]:
    if enforce_verbs is not None:
        return list(enforce_verbs)
    loader = (
        config_loader
        if config_loader is not None and hasattr(config_loader, "read_hooks_enforce_verbs")
        else _default_enforce_verbs_loader
    )
    try:
        return list(loader.read_hooks_enforce_verbs())
    except Exception as exc:  # noqa: BLE001 — fail-open to empty
        sys.stderr.write(
            f"[hooks_equivalence] enforce_verbs read failed, using []: {exc}\n"
        )
        return []


def describe_canary_edit(
    next_verb: Optional[str],
    *,
    current: list[str],
) -> str:
    """Return a human-readable YAML edit fragment for the operator.

    The returned string is the *entire* would-be ``enforce_verbs`` line
    (or block) after adding ``next_verb``, preserving ``CANARY_ORDER``.
    When ``next_verb`` is None the function emits a sentinel line so the
    operator can see that the canary is complete. This function never
    touches the real config file.
    """
    _validate_enforce_verbs(current)
    if next_verb is None:
        return (
            "# canary-enforce: all verbs remain enforced; no further flips required.\n"
            f"# current enforce_verbs: {sorted(current)}\n"
        )
    # Projected list = current + next_verb, deduped, then sorted by CANARY_ORDER.
    projected_set = {v for v in current if isinstance(v, str)} | {next_verb}
    projected = [v for v in CANARY_ORDER if v in projected_set]
    rendered = ", ".join(projected)
    return (
        "# canary-enforce stubbed flip (sub-plan 06 §5 item 4 — human_gate).\n"
        "# Operator: edit harness/config.yaml under the `hooks:` block to:\n"
        f"#   enforce_verbs: [{rendered}]\n"
        f"# next verb to enforce: {next_verb}\n"
    )


def evaluate_canary_flip(
    *,
    enforce_verbs: list[str] | None = None,
    min_clean_runs: int | None = None,
    reports_dir: "pathlib.Path | str | None" = None,
    config_loader: object | None = None,
) -> CanaryFlipDecision:
    """Plan (but never execute) the next canary enforce flip.

    Reads ``enforce_verbs`` from the passed list (or the config loader if
    None), runs the HOOK-52 diff gate, identifies the next verb per
    ``CANARY_ORDER``, and returns a ``CanaryFlipDecision``. The decision
    *never* mutates ``harness/config.yaml`` — the physical edit is an
    operator action after the P5 phase gate passes (sub-plan 06 §5
    item 4). ``human_gate_required`` is True whenever a verb remains to
    flip; it stays True across every trust-step, not just the first.
    """
    current = _resolve_enforce_verbs(enforce_verbs, config_loader)
    gate = check_diff_gate(
        min_clean_runs=min_clean_runs,
        reports_dir=reports_dir,
        config_loader=config_loader,
    )
    next_verb = canary_next_verb(current)

    if next_verb is None:
        return CanaryFlipDecision(
            verb=None,
            ready=False,
            reason=(
                "Canary complete — all verbs in CANARY_ORDER already appear "
                "in enforce_verbs; no further flips required."
            ),
            diff_gate=gate,
            human_gate_required=False,
            current_enforce_verbs=current,
        )

    if not gate.passed:
        return CanaryFlipDecision(
            verb=next_verb,
            ready=False,
            reason=(
                f"Diff gate not green for next flip {next_verb!r}: {gate.reason} "
                "No config change permitted until the shadow phase accumulates "
                "the required clean runs."
            ),
            diff_gate=gate,
            human_gate_required=True,
            current_enforce_verbs=current,
        )

    return CanaryFlipDecision(
        verb=next_verb,
        ready=True,
        reason=(
            f"Diff gate green; next verb {next_verb!r} is ready to enforce. "
            "Human operator must authorise the harness/config.yaml edit "
            "(sub-plan 06 §5 item 4 — first trust-step is human-only). "
            "This planner never applies the flip."
        ),
        diff_gate=gate,
        human_gate_required=True,
        current_enforce_verbs=current,
    )


# === Rollback wiring (HOOK-54) ==============================================


ROLLBACK_SIGNAL_PATH = "state/hooks/rollback_signal"

# Master plan 5.4 trigger matrix; unknown triggers normalise to
# "unknown" in emit_rollback_blocked_report but the raw name is still
# preserved in the report body for audit.
ROLLBACK_TRIGGERS: tuple[str, ...] = (
    "shadow_divergence_two_consecutive",
    "canary_error_not_in_mcp",
    "drain_consensus_regression",
    "agent_permission_denied_loop",
)


@dataclass
class RollbackOutcome:
    """End-to-end result of apply_rollback."""

    triggered: bool
    signal_source: str = ""
    previous_mode: str = ""
    blocked_report_path: str = ""
    trigger_reason: str = ""


def _resolve_signal_path(signal_path):
    if signal_path is None:
        return _project_dir() / ROLLBACK_SIGNAL_PATH
    return pathlib.Path(signal_path)


def rollback_signal_present(signal_path=None) -> bool:
    """Is the rollback-signal file on disk?"""
    return _resolve_signal_path(signal_path).exists()


def _parse_signal_body(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {"trigger": "unknown", "reason": "", "detail": ""}
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"trigger": "unknown", "reason": raw[:500], "detail": ""}
    if not isinstance(obj, dict):
        return {"trigger": "unknown", "reason": str(obj)[:500], "detail": ""}
    trigger = obj.get("trigger")
    if not isinstance(trigger, str) or not trigger:
        trigger = "unknown"
    return {
        "trigger": trigger,
        "reason": str(obj.get("reason") or ""),
        "detail": str(obj.get("detail") or ""),
    }


def read_rollback_signal(signal_path=None) -> dict:
    """Peek at the signal body without consuming it."""
    path = _resolve_signal_path(signal_path)
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write("[hooks_equivalence] rollback-signal read failed ({}): {}\n".format(path, exc))
        return {"trigger": "unknown", "reason": "", "detail": ""}
    return _parse_signal_body(raw)


def clear_rollback_signal(signal_path=None) -> bool:
    """Remove the signal file; return True iff it existed and was removed."""
    path = _resolve_signal_path(signal_path)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        sys.stderr.write("[hooks_equivalence] rollback-signal clear failed ({}): {}\n".format(path, exc))
        return False


_HOOKS_BLOCK_OPENER = re.compile(r"^hooks:\s*$", re.MULTILINE)
_MODE_LINE_RE = re.compile(
    r'^(?P<indent>\s+)mode:\s*(?P<quote>["' + "'" + r']?)(?P<value>\w+)(?P=quote)(?P<tail>.*)$',
    re.MULTILINE,
)
_TOP_LEVEL_KEY_RE = re.compile(r"^\S", re.MULTILINE)


def flip_hooks_mode_off(config_path) -> str:
    """Set hooks.mode to "off" in-place; return the prior value.

    Only touches the mode: line scoped under hooks: - siblings
    (enforce_verbs, shadow_dir, shadow_min_clean_runs) survive byte-identical.
    Gate 5 of impl_pre_write.py only blocks transitions into enforce -
    flipping enforce->off is agent-executable per master plan 5.4.
    """
    path = pathlib.Path(config_path)
    text = path.read_text(encoding="utf-8")

    hooks_match = _HOOKS_BLOCK_OPENER.search(text)
    if hooks_match is None:
        raise RuntimeError("flip_hooks_mode_off: no 'hooks:' block found in {}".format(path))
    block_start = hooks_match.end()

    rest = text[block_start:]
    next_top = _TOP_LEVEL_KEY_RE.search(rest)
    block_end_offset = next_top.start() if next_top else len(rest)
    block_end = block_start + block_end_offset

    block_text = text[block_start:block_end]
    mode_match = _MODE_LINE_RE.search(block_text)
    if mode_match is None:
        raise RuntimeError("flip_hooks_mode_off: no 'mode:' line under hooks: in {}".format(path))

    prior = mode_match.group("value")
    replacement = mode_match.group("indent") + 'mode: "off"' + mode_match.group("tail")
    new_block = block_text[:mode_match.start()] + replacement + block_text[mode_match.end():]
    new_text = text[:block_start] + new_block + text[block_end:]
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return prior


def _sanitise_ts_for_filename(ts: str) -> str:
    return ts.replace(":", "-")


def emit_rollback_blocked_report(*, trigger, reason, detail, blocked_dir, now_iso, previous_mode=None):
    """Write ROLLBACK-<ts>.md under blocked_dir; return the path."""
    if trigger not in ROLLBACK_TRIGGERS and trigger != "unknown":
        raise ValueError("Unknown trigger {!r}; must be one of {}".format(
            trigger, ROLLBACK_TRIGGERS + ("unknown",)))
    out_dir = pathlib.Path(blocked_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "ROLLBACK-" + _sanitise_ts_for_filename(now_iso)
    target = out_dir / (stem + ".md")
    tiebreak = 0
    while target.exists():
        tiebreak += 1
        target = out_dir / (stem + "-" + str(tiebreak) + ".md")

    prev_line = ""
    if previous_mode is not None:
        prev_line = "previous_mode: " + str(previous_mode) + "\n"

    reason_body = reason or "(no reason supplied)"
    detail_body = detail or "(no detail supplied)"

    body = (
        "---\n"
        "meta_task_type: harness_plumbing\n"
        "trigger: " + trigger + "\n"
        "timestamp: " + now_iso + "\n"
        + prev_line
        + "---\n"
        "\n"
        "# Rollback: " + trigger + "\n"
        "\n"
        "## Reason\n"
        + reason_body + "\n"
        "\n"
        "## Detail\n"
        + detail_body + "\n"
        "\n"
        "## Operator follow-up\n"
        "- Master plan 5.4 - review equivalence report, confirm no\n"
        "  regressions, and decide whether to re-attempt HOOK-20 diff-gate\n"
        "  before restoring mode=shadow.\n"
    )
    target.write_text(body, encoding="utf-8")
    return target


def _claim_signal_atomically(signal_path):
    """Atomic consume via rename-to-claimspace then unlink."""
    if not signal_path.exists():
        return None
    claim = signal_path.with_name(
        signal_path.name + ".claim-" + str(os.getpid()) + "-" + str(id(signal_path))
    )
    try:
        signal_path.rename(claim)
    except (FileNotFoundError, OSError):
        return None
    try:
        body = claim.read_text(encoding="utf-8")
    except OSError:
        body = ""
    try:
        claim.unlink()
    except OSError:
        pass
    return body


def apply_rollback(*, signal_path=None, config_path=None, blocked_dir=None, now_iso=None):
    """Detect + apply rollback end-to-end per master plan 5.4.

    Reads signal_path (default state/hooks/rollback_signal); when present
    it is claimed atomically, hooks.mode is flipped to off in config_path
    (default harness/config.yaml), and a ROLLBACK-<ts>.md file lands under
    blocked_dir (default state/tasks/blocked/) carrying meta_task_type:
    harness_plumbing. triggered=False on no-op so callers can poll cheaply.

    Race-safe: concurrent invocations see at most one triggered=True.
    """
    sig = _resolve_signal_path(signal_path)
    cfg = pathlib.Path(config_path) if config_path is not None else _project_dir() / _DEFAULT_CONFIG_REL
    blocked = pathlib.Path(blocked_dir) if blocked_dir is not None else _project_dir() / "state" / "tasks" / "blocked"
    now_ts = now_iso or now_iso_default()

    body = _claim_signal_atomically(sig)
    if body is None:
        return RollbackOutcome(triggered=False)

    parsed = _parse_signal_body(body)
    raw_trigger = parsed.get("trigger") or "unknown"
    reason = parsed.get("reason") or ""
    detail = parsed.get("detail") or ""

    if raw_trigger in ROLLBACK_TRIGGERS:
        trigger = raw_trigger
    else:
        trigger = "unknown"
        extra = "raw_trigger=" + str(raw_trigger)
        detail = extra + "\n" + detail if detail else extra

    try:
        previous_mode = flip_hooks_mode_off(cfg)
    except RuntimeError as exc:
        sys.stderr.write("[hooks_equivalence] rollback flip failed: {}\n".format(exc))
        previous_mode = "unknown"

    report = emit_rollback_blocked_report(
        trigger=trigger,
        reason=reason,
        detail=detail,
        blocked_dir=blocked,
        now_iso=now_ts,
        previous_mode=previous_mode,
    )

    return RollbackOutcome(
        triggered=True,
        signal_source=str(sig),
        previous_mode=previous_mode,
        blocked_report_path=str(report),
        trigger_reason=reason,
    )


# ---------------------------------------------------------------------------
# HOOK-55: drain-e2e primitives
#
# Replays brief_stab_001/003/005 end-to-end under hooks-shadow mode and diffs
# final artefacts (patch summary, unit-test count, state/tracks/*.jsonl event
# sequences). Baselines live alongside rollback_signal + equiv_report_* under
# state/hooks/. Sub-plan 06 §2 L3: the differential compares three fields, all
# three must match exactly (track_events as a multiset per §2 L3 rationale).
#
# run_drain_cycle accepts an injectable cycle_runner so unit/adv tests never
# spawn real Claude/Gemini. Regressions trigger rollback by writing
# state/hooks/rollback_signal with trigger="drain_consensus_regression" and
# letting HOOK-54 apply_rollback do the actual mode flip -- drain does not
# duplicate flip logic.
# ---------------------------------------------------------------------------


DRAIN_BASELINE_DIR = "state/hooks"

# Sub-plan 06 §1 step 5: the archived successful briefs chosen for the drain.
DRAIN_BRIEFS: tuple = ("stab_001", "stab_003", "stab_005")


@dataclass
class DrainArtefacts:
    """Three L3 differential fields captured at the end of a drain cycle."""

    patch_stat: str
    test_count: int
    track_events: list


@dataclass
class DrainBaseline:
    """Archived artefacts from a previously-successful cycle."""

    brief_id: str
    artefacts: DrainArtefacts


@dataclass
class DrainDivergence:
    """One field's disagreement between baseline and actual."""

    field: str
    baseline: Any
    actual: Any
    detail: str


@dataclass
class DrainReport:
    """End-to-end drain outcome. ``clean`` is True iff divergences is empty."""

    session_id: str
    brief_id: str
    clean: bool
    divergences: list
    generated_at: str

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "brief_id": self.brief_id,
            "clean": bool(self.clean),
            "divergences": [drain_divergence_to_dict(d) for d in self.divergences],
            "generated_at": self.generated_at,
        }


def drain_artefacts_to_dict(art: "DrainArtefacts") -> dict:
    return {
        "patch_stat": art.patch_stat,
        "test_count": int(art.test_count),
        "track_events": list(art.track_events),
    }


def drain_artefacts_from_dict(d: dict) -> "DrainArtefacts":
    return DrainArtefacts(
        patch_stat=str(d.get("patch_stat", "")),
        test_count=int(d.get("test_count", 0)),
        track_events=list(d.get("track_events", [])),
    )


def drain_divergence_to_dict(div: "DrainDivergence") -> dict:
    def _coerce(x):
        try:
            json.dumps(x, default=str)
            return x
        except (TypeError, ValueError) as exc:
            sys.stderr.write(
                f"[hooks_equivalence] _coerce JSON-encode failed for "
                f"{type(x).__name__}: {exc}\n"
            )
            return repr(x)

    return {
        "field": div.field,
        "baseline": _coerce(div.baseline),
        "actual": _coerce(div.actual),
        "detail": div.detail,
    }


def _summarise_patch(content: str) -> str:
    """Parse a unified-diff patch into a git-diff --stat-style summary.

    Keeps the drain module dependency-free (no subprocess into git; the
    drain never needs a live repo) and deterministic regardless of the
    caller's working directory.
    """

    if not content:
        return ""
    files = []
    current = None
    plus = 0
    minus = 0
    for ln in content.splitlines():
        if ln.startswith("diff --git a/"):
            if current is not None:
                files.append((current, plus, minus))
            parts = ln.split(" ")
            current = parts[2][2:] if len(parts) > 2 and parts[2].startswith("a/") else ""
            plus = 0
            minus = 0
            continue
        if ln.startswith("+++") or ln.startswith("---"):
            continue
        if ln.startswith("+"):
            plus += 1
        elif ln.startswith("-"):
            minus += 1
    if current is not None:
        files.append((current, plus, minus))
    if not files:
        return ""
    out_lines = []
    total_p = 0
    total_m = 0
    for path, p, m in files:
        out_lines.append(" {} | {}".format(path, p + m))
        total_p += p
        total_m += m
    file_word = "file changed" if len(files) == 1 else "files changed"
    out_lines.append(
        " {} {}, {} insertions(+), {} deletions(-)".format(
            len(files), file_word, total_p, total_m
        )
    )
    return "\n".join(out_lines)


def capture_drain_artefacts(
    *,
    patch_path: "pathlib.Path | str",
    test_count: int,
    tracks_path: "pathlib.Path | str",
) -> "DrainArtefacts":
    """Read a patch file + tracks .jsonl and return the three L3 fields.

    Missing patch/tracks files are tolerated (empty summary / empty event
    list). Malformed tracks rows are skipped. Negative test counts are
    rejected loudly; the caller should know how many tests pytest collected.
    """

    if isinstance(test_count, bool) or not isinstance(test_count, int):
        raise ValueError("test_count must be a non-negative int")
    if test_count < 0:
        raise ValueError("test_count must be a non-negative int")

    patch = pathlib.Path(patch_path)
    try:
        content = patch.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        content = ""
    stat = _summarise_patch(content)

    tracks = pathlib.Path(tracks_path)
    events: list = []
    try:
        raw = tracks.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        raw = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            events.append(obj)

    return DrainArtefacts(patch_stat=stat, test_count=test_count, track_events=events)


def _baseline_dir(baseline_dir) -> pathlib.Path:
    if baseline_dir is None:
        return _project_dir() / DRAIN_BASELINE_DIR
    return pathlib.Path(baseline_dir)


def _baseline_path(brief_id: str, baseline_dir=None) -> pathlib.Path:
    return _baseline_dir(baseline_dir) / ("drain_baseline_" + brief_id + ".json")


def save_drain_baseline(
    *,
    brief_id: str,
    artefacts: "DrainArtefacts",
    baseline_dir=None,
) -> pathlib.Path:
    """Persist a successful-cycle baseline under state/hooks/."""

    if brief_id not in DRAIN_BRIEFS:
        raise ValueError(
            "brief_id must be one of {}; got {}".format(DRAIN_BRIEFS, brief_id)
        )
    target_dir = _baseline_dir(baseline_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / ("drain_baseline_" + brief_id + ".json")
    payload = {
        "brief_id": brief_id,
        "artefacts": drain_artefacts_to_dict(artefacts),
        "generated_at": now_iso(),
    }
    target.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return target


def load_drain_baseline(
    *,
    brief_id: str,
    baseline_dir=None,
) -> "DrainBaseline | None":
    """Load a baseline; fail soft to None on missing/malformed/partial files."""

    if brief_id not in DRAIN_BRIEFS:
        return None
    target = _baseline_path(brief_id, baseline_dir)
    if not target.exists():
        return None
    try:
        raw = target.read_text(encoding="utf-8")
        obj = json.loads(raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    art_blob = obj.get("artefacts")
    if not isinstance(art_blob, dict):
        return None
    required = ("patch_stat", "test_count", "track_events")
    if not all(k in art_blob for k in required):
        return None
    try:
        art = drain_artefacts_from_dict(art_blob)
    except (TypeError, ValueError):
        return None
    stored_brief = obj.get("brief_id", brief_id)
    return DrainBaseline(brief_id=str(stored_brief), artefacts=art)


def load_drain_artefacts_from_path(path: "pathlib.Path | str") -> "DrainArtefacts":
    """Parse a standalone artefacts JSON file written by the cycle runner.

    The CLI --drain mode reads the actual artefacts from this shape. Missing
    required fields or malformed JSON raises -- operators should notice that
    their capture step produced garbage before trusting the differential.
    """

    p = pathlib.Path(path)
    raw = p.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("actual artefacts payload must be a JSON object")
    required = ("patch_stat", "test_count", "track_events")
    missing = [k for k in required if k not in obj]
    if missing:
        raise ValueError("actual artefacts missing fields: " + ",".join(missing))
    return drain_artefacts_from_dict(obj)


def _event_key(event) -> str:
    try:
        return json.dumps(event, sort_keys=True, default=str, ensure_ascii=True)
    except (TypeError, ValueError):
        return repr(event)


def _multiset_event_diff(a: list, b: list):
    ca = Counter(_event_key(e) for e in a)
    cb = Counter(_event_key(e) for e in b)
    only_a = list((ca - cb).elements())
    only_b = list((cb - ca).elements())
    return only_a, only_b


def compare_drain_artefacts(
    baseline: "DrainArtefacts",
    actual: "DrainArtefacts",
) -> list:
    """Return the list of DrainDivergence rows between baseline and actual.

    Empty list means the cycle was byte-for-byte clean. Ordering is stable
    (patch_stat, test_count, track_events) so callers can diff report files
    deterministically.
    """

    out: list = []
    if baseline.patch_stat != actual.patch_stat:
        out.append(
            DrainDivergence(
                field="patch_stat",
                baseline=baseline.patch_stat,
                actual=actual.patch_stat,
                detail="patch_stat differs",
            )
        )
    if int(baseline.test_count) != int(actual.test_count):
        out.append(
            DrainDivergence(
                field="test_count",
                baseline=int(baseline.test_count),
                actual=int(actual.test_count),
                detail="test_count differs",
            )
        )
    only_a, only_b = _multiset_event_diff(
        baseline.track_events or [], actual.track_events or []
    )
    if only_a or only_b:
        out.append(
            DrainDivergence(
                field="track_events",
                baseline=only_a,
                actual=only_b,
                detail=(
                    "track_events multiset diff: baseline_only="
                    + str(len(only_a))
                    + " actual_only="
                    + str(len(only_b))
                ),
            )
        )
    return out


def _drain_report_filename(brief_id: str, ts: str) -> str:
    return "drain_report_" + brief_id + "_" + _sanitise_ts_for_filename(ts) + ".json"


def run_drain_cycle(
    *,
    brief_id: str,
    cycle_runner,
    baseline: "DrainBaseline | None" = None,
    baseline_dir=None,
    output_dir=None,
    session_id: "str | None" = None,
    now_iso_fn=None,
) -> "DrainReport":
    """Execute one drain cycle and return a DrainReport.

    ``cycle_runner`` is a callable taking brief_id and returning DrainArtefacts.
    Tests inject a stub; CI wires the real run_consensus_patch.py invocation.
    Any exception from the runner is captured as a ``cycle_runner`` divergence
    so the DrainReport always has a stable shape.
    """

    if brief_id not in DRAIN_BRIEFS:
        raise ValueError(
            "brief_id must be one of {}; got {}".format(DRAIN_BRIEFS, brief_id)
        )

    now_fn = now_iso_fn or now_iso_default
    generated_at = now_fn()
    sid = session_id or ("drain-" + brief_id + "-" + _sanitise_ts_for_filename(generated_at))

    if baseline is None:
        baseline = load_drain_baseline(brief_id=brief_id, baseline_dir=baseline_dir)

    if baseline is None:
        report = DrainReport(
            session_id=sid,
            brief_id=brief_id,
            clean=False,
            divergences=[
                DrainDivergence(
                    field="baseline",
                    baseline=None,
                    actual=None,
                    detail="no drain baseline found for brief " + brief_id,
                )
            ],
            generated_at=generated_at,
        )
        _maybe_emit_drain_report(report, output_dir, generated_at)
        return report

    if baseline.brief_id != brief_id:
        raise ValueError(
            "baseline.brief_id={} does not match brief_id={}".format(
                baseline.brief_id, brief_id
            )
        )

    try:
        actual = cycle_runner(brief_id)
    except Exception as exc:  # noqa: BLE001 — surfacing, not silencing
        report = DrainReport(
            session_id=sid,
            brief_id=brief_id,
            clean=False,
            divergences=[
                DrainDivergence(
                    field="cycle_runner",
                    baseline=None,
                    actual=repr(exc),
                    detail="cycle_runner raised " + type(exc).__name__,
                )
            ],
            generated_at=generated_at,
        )
        _maybe_emit_drain_report(report, output_dir, generated_at)
        return report

    if not isinstance(actual, DrainArtefacts):
        raise TypeError("cycle_runner must return a DrainArtefacts instance")

    divs = compare_drain_artefacts(baseline.artefacts, actual)
    report = DrainReport(
        session_id=sid,
        brief_id=brief_id,
        clean=not divs,
        divergences=divs,
        generated_at=generated_at,
    )
    _maybe_emit_drain_report(report, output_dir, generated_at)
    return report


def _maybe_emit_drain_report(report: "DrainReport", output_dir, generated_at: str) -> None:
    if output_dir is None:
        out = _project_dir() / "state" / "hooks"
    else:
        out = pathlib.Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    fname = _drain_report_filename(report.brief_id, generated_at)
    (out / fname).write_text(
        json.dumps(report.to_dict(), sort_keys=True),
        encoding="utf-8",
    )


def fire_drain_rollback(
    report: "DrainReport",
    *,
    signal_path=None,
) -> bool:
    """Write state/hooks/rollback_signal with trigger=drain_consensus_regression.

    Returns True iff a new signal was written. No-op on clean reports and on
    reports where a signal is already present -- HOOK-54 apply_rollback owns
    consumption, so fire_drain_rollback must not stomp on an unconsumed one.
    """

    if report.clean:
        return False
    sig = _resolve_signal_path(signal_path)
    if sig.exists():
        return False
    sig.parent.mkdir(parents=True, exist_ok=True)
    diverged_fields = sorted({d.field for d in report.divergences}) or ["unknown"]
    payload = {
        "trigger": "drain_consensus_regression",
        "reason": (
            "drain regression on brief " + str(report.brief_id) + ": "
            + ",".join(diverged_fields)
        ),
        "detail": (
            "session_id=" + str(report.session_id)
            + " divergence_count=" + str(len(report.divergences))
        ),
    }
    sig.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return True


def now_iso_default() -> str:
    """Alias for now_iso() - tests pass an explicit now_iso without
    touching the shadow-writer's own timestamp source."""
    return now_iso()


def main(argv: "list[str] | None" = None) -> int:
    """CLI entrypoint for the HOOK-51 comparator, HOOK-52 diff gate,
    and HOOK-53 canary-enforce planner.

    Modes:

    * Positional ``session_id`` — runs the HOOK-51 comparator end-to-end
      and exits 0 when ``match_rate == 1.0 and len(divergences) == 0``,
      else 1.
    * ``--gate`` — runs the HOOK-52 diff gate over accumulated
      ``equiv_report_*.json`` files and exits 0 on N consecutive clean
      runs, else 1.
    * ``--canary`` — runs the HOOK-53 planner and exits:
        0 — no verbs remain to flip (canary complete),
        1 — diff gate not green,
        2 — human_gate required (verb identified, gate passes, operator
            must authorise the config edit manually — this CLI never
            writes to harness/config.yaml).

    Examples::

        python -m harness.hooks_equivalence sess-abc --shadow-dir DIR
        python -m harness.hooks_equivalence --gate --min-clean-runs 3
        python -m harness.hooks_equivalence --canary --min-clean-runs 3
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="harness.hooks_equivalence",
        description=(
            "Compare shadow vs MCP-era audit log for one session (positional "
            "session_id) or verify the shadow→enforce diff gate (--gate)."
        ),
    )
    parser.add_argument("session_id", nargs="?", default=None)
    parser.add_argument("--shadow-dir", default=None)
    parser.add_argument("--audit-root", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--agent", default=None)
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Run the HOOK-52 diff gate instead of the per-session comparator.",
    )
    parser.add_argument(
        "--canary",
        action="store_true",
        help="Run the HOOK-53 canary-enforce planner (read-only; never writes config).",
    )
    parser.add_argument("--reports-dir", default=None)
    parser.add_argument("--min-clean-runs", type=int, default=None)
    parser.add_argument(
        "--enforce-verbs",
        default=None,
        help="Comma-separated override of hooks.enforce_verbs (test/debug only).",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Apply the HOOK-54 rollback procedure when state/hooks/rollback_signal is present.",
    )
    parser.add_argument("--signal-path", default=None)
    parser.add_argument("--config-path", default=None)
    parser.add_argument("--blocked-dir", default=None)
    parser.add_argument(
        "--drain",
        nargs="?",
        const="__missing__",
        default=None,
        help="Run the HOOK-55 drain differential for the named archived brief.",
    )
    parser.add_argument(
        "--actual-path",
        default=None,
        help="Path to a JSON file emitted by the drain cycle runner (patch_stat, test_count, track_events).",
    )
    parser.add_argument(
        "--baseline-dir",
        default=None,
        help="Override the drain baseline directory (default state/hooks/).",
    )
    parser.add_argument(
        "--emit-rollback",
        action="store_true",
        help="On drain regression, write state/hooks/rollback_signal with trigger=drain_consensus_regression.",
    )
    parser.add_argument(
        "--output-drain-dir",
        default=None,
        help="If set, write drain_report_<brief>_<ts>.json into this directory.",
    )
    args = parser.parse_args(argv)

    if args.drain is not None:
        if args.drain == "__missing__":
            parser.error("--drain requires a brief_id (one of {})".format(DRAIN_BRIEFS))
        if args.drain not in DRAIN_BRIEFS:
            parser.error(
                "--drain: unknown brief {!r}; expected one of {}".format(
                    args.drain, DRAIN_BRIEFS
                )
            )
        if not args.actual_path:
            parser.error("--drain requires --actual-path to a cycle-runner output JSON")
        try:
            actual_art = load_drain_artefacts_from_path(args.actual_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            sys.stderr.write(
                "[hooks_equivalence] --drain: failed to load --actual-path {}: {}\n".format(
                    args.actual_path, exc
                )
            )
            return 2
        report = run_drain_cycle(
            brief_id=args.drain,
            cycle_runner=lambda _b, art=actual_art: art,
            baseline_dir=args.baseline_dir,
            output_dir=args.output_drain_dir,
        )
        sys.stderr.write(
            "[hooks_equivalence] drain brief={} clean={} divergences={}\n".format(
                report.brief_id, report.clean, len(report.divergences)
            )
        )
        if report.clean:
            return 0
        sys.stdout.write(
            json.dumps(report.to_dict(), sort_keys=True) + "\n"
        )
        if args.emit_rollback:
            fired = fire_drain_rollback(report)
            sys.stderr.write(
                "[hooks_equivalence] drain rollback fired={}\n".format(fired)
            )
        return 1

    if args.gate:
        result = check_diff_gate(
            min_clean_runs=args.min_clean_runs,
            reports_dir=args.reports_dir,
        )
        sys.stderr.write(
            f"[hooks_equivalence] diff-gate passed={result.passed} "
            f"clean_run_count={result.clean_run_count} "
            f"required={result.required_clean_runs} "
            f"reason={result.reason!r}\n"
        )
        return 0 if result.passed else 1

    if args.canary:
        override_verbs: "list[str] | None" = None
        if args.enforce_verbs is not None:
            override_verbs = [
                v.strip() for v in args.enforce_verbs.split(",") if v.strip()
            ]
        decision = evaluate_canary_flip(
            enforce_verbs=override_verbs,
            min_clean_runs=args.min_clean_runs,
            reports_dir=args.reports_dir,
        )
        edit_fragment = describe_canary_edit(
            decision.verb, current=decision.current_enforce_verbs
        )
        sys.stdout.write(edit_fragment)
        sys.stderr.write(
            f"[hooks_equivalence] canary verb={decision.verb!r} "
            f"ready={decision.ready} human_gate_required={decision.human_gate_required} "
            f"reason={decision.reason!r}\n"
        )
        if decision.verb is None:
            return 0
        if not decision.ready:
            return 1
        return 2

    if args.rollback:
        outcome = apply_rollback(
            signal_path=args.signal_path,
            config_path=args.config_path,
            blocked_dir=args.blocked_dir,
        )
        if outcome.triggered:
            # Surface trigger name by reading it back from the blocked report
            # so the operator sees what fired without opening the file.
            trigger_label = ""
            try:
                import re as _re
                body_text = pathlib.Path(outcome.blocked_report_path).read_text(encoding="utf-8")
                m = _re.search(r"^trigger:\s*(\S+)", body_text, _re.MULTILINE)
                if m:
                    trigger_label = m.group(1)
            except Exception:
                trigger_label = ""
            sys.stdout.write(
                "rollback applied: trigger={} previous_mode={} blocked_report={}\n".format(
                    trigger_label or "unknown",
                    outcome.previous_mode,
                    outcome.blocked_report_path,
                )
            )
            sys.stderr.write(
                "[hooks_equivalence] rollback triggered previous_mode={} report={} trigger_reason={}\n".format(
                    outcome.previous_mode, outcome.blocked_report_path, outcome.trigger_reason
                )
            )
        else:
            sys.stdout.write("rollback noop: no signal present\n")
            sys.stderr.write("[hooks_equivalence] rollback noop (no signal)\n")
        return 0

    if args.session_id is None:
        parser.error("session_id is required unless --gate, --canary, --rollback, or --drain is set")

    report = run_comparison(
        args.session_id,
        shadow_dir=args.shadow_dir,
        audit_root=args.audit_root,
        output_dir=args.output_dir,
        agent=args.agent,
    )
    clean = report.match_rate == 1.0 and not report.divergences
    sys.stderr.write(
        f"[hooks_equivalence] session={report.session_id} "
        f"match_rate={report.match_rate:.3f} "
        f"divergences={len(report.divergences)}\n"
    )
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
