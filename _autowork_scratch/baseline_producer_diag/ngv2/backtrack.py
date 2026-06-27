"""ngv2.backtrack -- deterministic stateful-retry / backtracking validation shell.

This module is a PURE deterministic orchestration shell. It never imports a
sibling Epic-4 leaf (ast_constraint, ast_verifier, z3_bridge) and never calls a
real solver, z3, or an LLM. Every verification decision is delegated to an
INJECTED verifier callable (the verification seam) supplied by the caller.

When generated code fails symbolic validation, ``BacktrackContext`` accumulates
the violations, exposes them as negative-constraint text for the next attempt,
and emits a structured BACKTRACK token. No clock, no file IO, no network --
identical inputs always produce identical outputs.
"""
from typing import Any, Callable, Dict, List, Optional, Tuple
DEFAULT_CONSTRAINT_SET: str = 'grounding'
BACKTRACK_TOKEN_FIELDS: Tuple[str, ...] = ('event', 'attempt', 'backtrack_count', 'max_retries', 'total_violations', 'violations', 'component')
Violation = Dict[str, Any]
Verifier = Callable[..., List[Violation]]

def _format_violation(violation: Violation) -> str:
    """Render one violation as a single negative-constraint line."""
    return 'AVOID: {message} (rule: {rule}, line {line})'.format(message=violation.get('message', ''), rule=violation.get('rule', ''), line=violation.get('line', ''))

def _format_violations(violations: List[Violation]) -> str:
    """Render an ordered list of violations as newline-joined constraint text."""
    return '\n'.join((_format_violation(v) for v in violations))

class BacktrackError(Exception):
    """Raised when an attempt fails verification.

    Carries the violations that triggered the failure and the attempt number on
    which they occurred. ``as_constraint`` renders them as negative-constraint
    text for the next generation attempt.
    """

    def __init__(self, violations: Optional[List[Violation]]=None, attempt: int=0) -> None:
        self.violations: List[Violation] = list(violations) if violations else []
        self.attempt: int = attempt
        super().__init__(self.as_constraint())

    def as_constraint(self) -> str:
        return _format_violations(self.violations)

class BacktrackContext:
    """Stateful retry/backtracking shell driven by injected verifier seams.

    Parameters
    ----------
    max_retries:
        Maximum number of attempts before the shell gives up.
    ast_verifier:
        Injected callable invoked for every ``validate`` call. Returns a list of
        violations (empty list == clean).
    z3_bridge:
        Optional injected callable invoked only when a ``z3_state`` is supplied
        to ``validate``. Returns a list of violations (empty list == clean).
    """

    def __init__(self, max_retries: int=3, ast_verifier: Optional[Verifier]=None, z3_bridge: Optional[Verifier]=None) -> None:
        self.max_retries: int = max_retries
        self.ast_verifier: Optional[Verifier] = ast_verifier
        self.z3_bridge: Optional[Verifier] = z3_bridge
        self.attempt: int = 0
        self.backtrack_count: int = 0
        self.gave_up: bool = False
        self._history: List[Violation] = []

    def _run(self, verifier: Optional[Verifier], *args: Any) -> List[Violation]:
        """Invoke an injected verifier seam deterministically."""
        if verifier is None:
            return []
        result = verifier(*args, attempt=self.attempt)
        return list(result) if result else []

    def validate(self, code: str, z3_state: Optional[Dict[str, Any]]=None) -> None:
        """Validate ``code`` via the injected seams.

        Returns ``None`` on success. On any violation, accumulates the violations
        into history and raises ``BacktrackError``. The z3 bridge runs only when a
        ``z3_state`` is supplied and a bridge was injected.
        """
        self.attempt += 1
        violations: List[Violation] = self._run(self.ast_verifier, code)
        if not violations and z3_state is not None and (self.z3_bridge is not None):
            violations = self._run(self.z3_bridge, z3_state)
        if violations:
            self._history.extend(violations)
            if self.attempt >= self.max_retries:
                self.gave_up = True
            raise BacktrackError(violations=violations, attempt=self.attempt)
        return None

    def get_negative_constraints(self) -> str:
        """Render all accumulated violations as negative-constraint text."""
        return _format_violations(self._history)

    def emit_backtrack_token(self) -> Dict[str, Any]:
        """Emit a deterministic BACKTRACK token.

        Each call bumps ``backtrack_count``; every other field is a pure function
        of the current accumulated state (no clock, no randomness).
        """
        self.backtrack_count += 1
        violations = list(self._history)
        values = (('event', 'BACKTRACK'), ('attempt', self.attempt), ('backtrack_count', self.backtrack_count), ('max_retries', self.max_retries), ('total_violations', len(violations)), ('violations', violations), ('component', 'backtrack_context'))
        return dict(values)

    def __enter__(self) -> 'BacktrackContext':
        self.attempt = 0
        self.backtrack_count = 0
        self.gave_up = False
        self._history = []
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if exc_type is not None and issubclass(exc_type, BacktrackError):
            self.emit_backtrack_token()
        return False

def make_mock_verifier(*violations: Violation) -> Verifier:
    """Build a verifier seam that always returns the same fixed violations."""
    fixed: List[Violation] = list(violations)

    def _verify(_target: Any=None, attempt: Optional[int]=None, **_kwargs: Any) -> List[Violation]:
        return list(fixed)
    return _verify

def make_scripted_verifier(schedule: Dict[int, List[Violation]]) -> Verifier:
    """Build a verifier seam that returns violations keyed by attempt number."""
    table: Dict[int, List[Violation]] = dict(schedule)

    def _verify(_target: Any=None, attempt: Optional[int]=None, **_kwargs: Any) -> List[Violation]:
        return list(table.get(attempt, []))
    return _verify