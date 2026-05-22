"""Operator behavioural pin for the clean-room rebuild of task_id_normalizer.

``strip_decomposition_suffixes`` is oracle-USABLE but its merged==original fuzz is
VACUOUS: the distinguishing branch only fires on task_ids that END with one of the
fixed decomposition suffixes (``-reviewed``/``-compose``/...), which random fuzz
strings essentially never produce. So a blind reconstruction that fails to strip
could pass the fuzz silently. These per-unit-named pins (derived from + verified
against the real original) gate the reconstruction. C9.17c LAW.
"""

from harness.task_id_normalizer import strip_decomposition_suffixes


def test_strip_decomposition_suffixes_removes_single():
    assert strip_decomposition_suffixes("foo-reviewed") == "foo"
    assert strip_decomposition_suffixes("mytask-compose") == "mytask"


def test_strip_decomposition_suffixes_removes_chain_repeatedly():
    assert strip_decomposition_suffixes("foo-general-reviewed") == "foo"
    assert (
        strip_decomposition_suffixes("a-single_element-type_error-general") == "a"
    )
    assert strip_decomposition_suffixes("mytask-boundary-empty_input") == "mytask"


def test_strip_decomposition_suffixes_no_suffix_unchanged():
    assert strip_decomposition_suffixes("plain-bar") == "plain-bar"
    assert strip_decomposition_suffixes("") == ""


def test_strip_decomposition_suffixes_only_at_end():
    # An interior suffix-like substring is NOT stripped (anchored to end).
    assert strip_decomposition_suffixes("foo-reviewed-x") == "foo-reviewed-x"
    assert strip_decomposition_suffixes("-reviewed") == ""
