import sys
sys.path.append('.')
from harness.boundary_smoothing import align_and_deduplicate_patches, apply_with_sliding_retry

source_code = """class MyClass:
    def method_one(self):
        pass

    @decorator
    def method_two(self):
        print("two")
"""

# Test 1: Misaligned indent + duplicate signature
patch1 = """def method_two(self):
  print("two updated")
  print("more")
"""

# Test 2: Overlapping decorator
patch2 = """    @decorator
    def method_two(self):
        print("two updated")
"""

print("--- TEST 1 ---")
try:
    res1 = align_and_deduplicate_patches(source_code, patch1)
    print(res1)
except Exception as e:
    print(f"Error 1: {e}")

print("--- TEST 2 ---")
try:
    res2 = align_and_deduplicate_patches(source_code, patch2)
    print(res2)
except Exception as e:
    print(f"Error 2: {e}")

print("--- TEST 3 (sliding retry) ---")
try:
    res3 = apply_with_sliding_retry(source_code, patch1, delta=2)
    print(res3)
except Exception as e:
    print(f"Error 3: {e}")
