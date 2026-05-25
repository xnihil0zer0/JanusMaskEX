from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

def validate_nonempty(xs):
    return xs[0] is not None

@given(xs=st.lists(st.integers(), max_size=4))
@settings(
    max_examples=200,
    deadline=1000,
    database=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much]
)
def run_fuzz(xs):
    validate_nonempty(xs)

try:
    run_fuzz()
except Exception as e:
    print("Caught:", type(e))
