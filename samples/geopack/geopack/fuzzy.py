"""An UN-typed function in a TEST-LESS module (the test-author role fills it)."""


def clamp(value, low, high):
    """Clamp ``value`` into the inclusive range [``low``, ``high``]."""
    if value < low:
        return low
    if value > high:
        return high
    return value
