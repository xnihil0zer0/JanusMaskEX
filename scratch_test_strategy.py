from __future__ import annotations
from typing import Any
import sys
from hypothesis import strategies as st

def _strategy_for_annotation(annotation: str) -> st.SearchStrategy[Any] | None:
    a = annotation.strip()
    if a.startswith('typing.'):
        a = a[len('typing.'):]
    a_normalized = "".join(a.split())
    
    if a_normalized in ('str', 'builtins.str', 'Text'):
        return st.text(alphabet=st.characters(blacklist_categories=('Cs',)))
    if a_normalized in ('bool', 'builtins.bool'):
        return st.booleans()
    if a_normalized in ('int', 'builtins.int'):
        return st.integers()
    if a_normalized in ('list', 'List') or a_normalized.startswith('list[') or a_normalized.startswith('List['):
        return st.lists(
            st.one_of(st.integers(), st.text(max_size=8), st.none()),
            max_size=4,
        )
    if a_normalized in ('dict', 'Dict') or a_normalized.startswith('dict[') or a_normalized.startswith('Dict['):
        return st.dictionaries(
            st.text(max_size=8),
            st.one_of(st.none(), st.integers(), st.text(max_size=8)),
            max_size=4,
        )
    return None

if __name__ == '__main__':
    test_cases = [
        ('str', True),
        ('builtins.str', True),
        ('typing.Text', True),
        ('bool', True),
        ('int', True),
        ('list', True),
        ('List', True),
        ('typing.List[int]', True),
        ('List [ str ]', True),
        ('dict', True),
        ('Dict', True),
        ('typing.Dict[str, int]', True),
        ('socket.AddressFamily', False),
    ]
    for ann, expected in test_cases:
        res = _strategy_for_annotation(ann)
        is_strat = isinstance(res, st.SearchStrategy)
        assert is_strat == expected, f"Failed for {ann}: expected {expected}, got {res}"
        if is_strat:
            val = res.example()
            print(f"{ann} -> strategy -> example: {val!r}")
        else:
            print(f"{ann} -> None")
    print("All checks passed successfully!")
