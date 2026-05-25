from hypothesis import given, settings
from hypothesis import strategies as st

@given()
@settings(max_examples=10, database=None)
def run_fuzz():
    print("running fuzz")

try:
    run_fuzz()
except Exception as e:
    print("Error:", type(e), e)
