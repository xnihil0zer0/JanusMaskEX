from typing import Callable, Any

def _meta_for(fn: Callable[..., Any]) -> dict[str, Any]:
    meta = getattr(fn, "_narrow_fuzz_meta", {})
    if isinstance(meta, dict):
        return meta
    return {}

# Simple test cases
def test_meta_for():
    def undecorated():
        pass
    assert _meta_for(undecorated) == {}

    def decorated():
        pass
    decorated._narrow_fuzz_meta = {"skip": True, "timeout": 10.0}
    assert _meta_for(decorated) == {"skip": True, "timeout": 10.0}

    def decorated_bad():
        pass
    decorated_bad._narrow_fuzz_meta = "not-a-dict"
    assert _meta_for(decorated_bad) == {}

    print("All tests passed!")

if __name__ == "__main__":
    test_meta_for()
