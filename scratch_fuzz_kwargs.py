from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

def my_func(a, b):
    if a == b:
        raise ValueError("Match!")

strategies = {
    "a": st.integers(),
    "b": st.integers()
}

def make_fuzz_target(name, fn, strategies, timeout):
    def test_target(**kwargs):
        fn(**kwargs)
    test_target.__name__ = name
    test_target.__qualname__ = name
    
    decorated = given(**strategies)(
        settings(
            max_examples=200,
            deadline=int(timeout * 1000) if timeout else None,
            database=None,
            suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much]
        )(test_target)
    )
    return decorated

run_fuzz = make_fuzz_target("my_dynamic_name", my_func, strategies, 5.0)

try:
    run_fuzz()
except Exception as e:
    print("Caught error:", type(e))
    print("Notes:", getattr(e, "__notes__", []))
