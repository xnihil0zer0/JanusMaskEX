"""C9.18 / session #44 P0 KEYSTONE: ``task._k_expr`` must be CLASS-AWARE for methods.

The pre-#44 selector reduced every method to a bare ``test_<method>_`` token, so
two same-named methods in different classes (every project's ``__init__``) shared
ONE ``-k`` expression -- verifying one ran the OTHER's scoped test, which
false-failed while that sibling was still a ``raise NotImplementedError`` stub and
cascaded to dependents (witnessed #43: brief_loader's ``BriefValidationError.__init__``
+ ``BriefTooLargeError.__init__`` collapsing into ``_parse_frontmatter``). This was
the last structural blocker for clean-room rebuilding ANY OOP/multi-class project.

The fix anchors a method to the CLASS-FIRST convention
``test_<clstoken>_<method>_<behaviour>`` so same-named methods in different classes
get DISJOINT selectors, while a single method never pulls a SIBLING of its own
class. Free functions and whole_class units (cls omitted) keep the prior form.
"""
from harness.rebuild import task


def _selected(k_expr, names):
    """Mimic ``pytest -k``: case-insensitive substring match of any or-joined token."""
    toks = [t.strip().lower() for t in k_expr.strip("'").split(" or ")]
    return {n for n in names if any(t in n.lower() for t in toks)}


def test_kexpr_same_named_methods_get_disjoint_selectors():
    a = task._k_expr("__init__", cls="BriefValidationError")
    b = task._k_expr("__init__", cls="BriefTooLargeError")
    assert a != b
    names = [
        "test_briefvalidationerror_init_stores_message",
        "test_brieftoolargeerror_init_carries_actual_bytes",
    ]
    assert _selected(a, names) == {"test_briefvalidationerror_init_stores_message"}
    assert _selected(b, names) == {"test_brieftoolargeerror_init_carries_actual_bytes"}


def test_kexpr_method_selects_only_its_own_class_and_method():
    k = task._k_expr("to_dict", cls="Widget")
    names = [
        "test_widget_to_dict_roundtrips",
        "test_widget_from_dict_builds",    # sibling METHOD, same class
        "test_gadget_to_dict_roundtrips",  # same method NAME, other class
    ]
    assert _selected(k, names) == {"test_widget_to_dict_roundtrips"}


def test_kexpr_dunder_method_strips_underscores_keeps_class():
    assert task._k_expr("__post_init__", cls="Target") == "'test_target_post_init_'"


def test_kexpr_function_form_unchanged_without_cls():
    # Backward compat: free functions keep the anchored function + CamelClass form.
    assert task._k_expr("is_prime") == "'test_is_prime_ or TestIsPrime'"


def test_kexpr_whole_class_passes_cls_none_and_keeps_class_form():
    # whole_class units pass cls=None (the build_unit_task/_run_unit_tests guard),
    # so the class NAME as ``name`` selects every method test of the class together.
    k = task._k_expr("PlanningBrief")
    names = ["test_planningbrief_to_agent_prompt_x", "test_planningbrief_is_frozen"]
    assert _selected(k, names) == set(names)


def test_cls_token_normalizes_camel_and_underscores():
    assert task._cls_token("BriefValidationError") == "briefvalidationerror"
    assert task._cls_token("_Private_Helper_") == "privatehelper"
