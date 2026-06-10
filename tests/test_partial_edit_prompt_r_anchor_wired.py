"""RED oracle — the PARTIAL-EDIT DISPATCH prompt must document the R-ANCHOR
pattern for ADDING brand-new top-level symbols.

Root cause under test: ``prepare_task_prompt``'s PARTIAL-EDIT DISPATCH prompt
string (harness/orchestrator.py) documents only how to REPLACE an existing
``kind:'symbol'`` block. It says nothing about how to ADD a brand-new
top-level def/class/constant. So an additive EDIT leaf (e.g. "add 3 new
functions to ngv2/debate_router.py") emits patch entries naming NOT-YET-
EXISTING symbols, and ``git_integration._apply_symbol_patch`` — which can only
slice-replace an EXISTING symbol — raises ``KeyError`` ("patch apply failed").

The harness already supports additive edits via the R-ANCHOR mechanism
(PHASE_R_ANCHORED_PATCH in ``_apply_symbol_patch``): a ``kind:'symbol'`` entry
whose ``name`` is an EXISTING top-level anchor, whose ``code`` reproduces that
anchor PLUS the new top-level symbol(s) as "extras"; the harness inserts the
extras immediately before the anchor and preserves the rest of the file.

Contract pinned here: the PARTIAL-EDIT prompt returned by ``prepare_task_prompt``
for a task that gets the partial-edit block MUST now also contain guidance that
documents this additive R-anchor pattern. Specifically the prompt must:
  - mention the R-ANCHOR mechanism by name;
  - state that a 'symbol' patch can ONLY replace a symbol that ALREADY EXISTS;
  - explain anchoring new symbols on an existing top-level symbol;
  - include a concrete worked example anchoring NEW ``foo``/``bar`` on existing
    ``baz``.

A hermetic SELF EDIT task (working_dir=None, an existing repo .py target,
meta_task_type='validation') is used so the PARTIAL-EDIT block is present and
the test does not couple to any external checkout.

RED today: HEAD's PARTIAL-EDIT string lacks all of these markers.
"""
import os

import pytest

from harness.orchestrator import prepare_task_prompt

_PARTIAL_MARKER = "PARTIAL-EDIT DISPATCH"


def _self_edit_partial_prompt() -> str:
    """Return the PARTIAL-EDIT prompt for a hermetic SELF EDIT task."""
    rel = os.path.join("harness", "orchestrator.py")
    task = {
        "task_id": "r-anchor-prompt-probe",
        "working_dir": None,
        "files_touched": [rel],
        "meta_task_type": "validation",
        "specification": "edit a large self file in place",
    }
    return prepare_task_prompt(task)


_self_edit_partial_prompt.__test__ = False


def test_partial_edit_prompt_block_is_present():
    """Sanity guard: the probe task really does receive the PARTIAL-EDIT block.

    Passes before and after the fix; guarantees the marker assertions below are
    exercising the right code path (not a false-green from an absent block).
    """
    prompt = _self_edit_partial_prompt()
    assert _PARTIAL_MARKER in prompt


def test_partial_edit_prompt_documents_r_anchor_mechanism():
    """The prompt must name the R-ANCHOR additive mechanism. RED today."""
    prompt = _self_edit_partial_prompt()
    assert "R-ANCHOR" in prompt, (
        "PARTIAL-EDIT prompt must document the R-ANCHOR additive pattern by "
        "name so additive EDIT leaves know how to add brand-new top-level "
        "symbols instead of naming a not-yet-existing symbol (which fails)"
    )


def test_partial_edit_prompt_states_symbol_must_already_exist():
    """The prompt must warn that 'symbol' only replaces an EXISTING symbol.

    RED today: nothing in the PARTIAL-EDIT string says a named symbol must
    already exist, so additive leaves emit not-yet-existing names and fail.
    """
    prompt = _self_edit_partial_prompt()
    assert "already exist" in prompt, (
        "PARTIAL-EDIT prompt must state that a 'symbol' patch can ONLY replace "
        "a symbol that ALREADY EXISTS"
    )


def test_partial_edit_prompt_includes_anchor_example():
    """The prompt must include the concrete foo/bar-anchored-on-baz example.

    RED today: no worked additive example exists in the PARTIAL-EDIT string.
    """
    prompt = _self_edit_partial_prompt()
    # The worked example adds new functions ``foo`` and ``bar`` anchored on an
    # existing top-level symbol ``baz``.
    assert "baz" in prompt, (
        "PARTIAL-EDIT prompt must include a concrete R-anchor example whose "
        "anchor symbol is 'baz' and whose new symbols are 'foo'/'bar'"
    )
    assert "foo" in prompt and "bar" in prompt, (
        "the R-anchor worked example must add new symbols 'foo' and 'bar'"
    )
