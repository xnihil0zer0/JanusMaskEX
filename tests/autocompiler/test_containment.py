"""RED oracle — authoritative contract for autocompiler/containment.py (leaf ac-containment).

Contract: ``extract_evolve_ranges(src) -> list[tuple[int, int]]`` scans COMMENT
tokens (tokenize-based, the JANUSMASK_DELETE precedent) for paired
``# JM-EVOLVE-BLOCK-START`` / ``# JM-EVOLVE-BLOCK-END`` markers and returns
1-based inclusive (start_line, end_line) ranges covering the lines BETWEEN the
two marker comments. Malformed marker structure (START without END, END before
START, unparseable source) => [] (fail-closed). ``check_write_containment(
parent_src, cand_src, ranges) -> result`` returns a GateResult-shaped object
(attrs ``ok`` bool, ``reason`` str): ok=True when every changed/added line of
the candidate (relative to the parent) falls inside one of ``ranges``;
ok=False with a non-empty reason when anything outside the ranges changed
(e.g. a new top-level def appended after the block). Empty ``ranges`` with ANY
change => ok=False. Identical sources => ok=True. Pure, never raises.
"""
from autocompiler.containment import extract_evolve_ranges, check_write_containment

PARENT = (
    'def f():\n'                       # 1
    '    # JM-EVOLVE-BLOCK-START\n'    # 2
    '    total = 1\n'                  # 3
    '    # JM-EVOLVE-BLOCK-END\n'      # 4
    '    return total\n'               # 5
)


def test_extract_single_range_between_markers():
    assert extract_evolve_ranges(PARENT) == [(3, 3)]


def test_extract_two_blocks():
    src = (
        '# JM-EVOLVE-BLOCK-START\n'    # 1
        'a = 1\n'                      # 2
        '# JM-EVOLVE-BLOCK-END\n'      # 3
        'b = 2\n'                      # 4
        '# JM-EVOLVE-BLOCK-START\n'    # 5
        'c = 3\n'                      # 6
        'd = 4\n'                      # 7
        '# JM-EVOLVE-BLOCK-END\n'      # 8
    )
    assert extract_evolve_ranges(src) == [(2, 2), (6, 7)]


def test_extract_malformed_unclosed_is_empty():
    assert extract_evolve_ranges('# JM-EVOLVE-BLOCK-START\nx = 1\n') == []


def test_extract_end_before_start_is_empty():
    assert extract_evolve_ranges('# JM-EVOLVE-BLOCK-END\nx = 1\n# JM-EVOLVE-BLOCK-START\n') == []


def test_extract_marker_in_string_literal_ignored():
    src = 's = "# JM-EVOLVE-BLOCK-START"\n'
    assert extract_evolve_ranges(src) == []


def test_extract_unparseable_source_is_empty():
    assert extract_evolve_ranges('def broken(:\n') == []


def test_containment_inside_range_ok():
    cand = PARENT.replace('total = 1', 'total = 2')
    res = check_write_containment(PARENT, cand, extract_evolve_ranges(PARENT))
    assert res.ok is True


def test_containment_added_def_outside_range_rejected():
    cand = PARENT + '\n\ndef sneaky():\n    return 99\n'
    res = check_write_containment(PARENT, cand, extract_evolve_ranges(PARENT))
    assert res.ok is False
    assert res.reason


def test_containment_edit_outside_range_rejected():
    cand = PARENT.replace('return total', 'return total + 1')
    res = check_write_containment(PARENT, cand, extract_evolve_ranges(PARENT))
    assert res.ok is False


def test_containment_no_ranges_any_change_rejected():
    res = check_write_containment('x = 1\n', 'x = 2\n', [])
    assert res.ok is False


def test_containment_identical_ok():
    res = check_write_containment(PARENT, PARENT, extract_evolve_ranges(PARENT))
    assert res.ok is True
