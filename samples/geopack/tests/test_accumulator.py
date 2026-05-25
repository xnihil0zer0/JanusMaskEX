from geopack.accumulator import Accumulator


def test_accumulator_lifecycle():
    # ONE multi-method test exercising __init__, add, and mean together -- a
    # stateful class that per-method reconstruction cannot verify (siblings are
    # still stubs when the first method is gated), so it must rebuild whole-class.
    a = Accumulator(10)
    a.add(5)
    a.add(15)
    assert a.total == 30
    assert a.count == 2
    assert a.mean() == 15.0


def test_accumulator_empty():
    a = Accumulator()
    assert a.total == 0
    assert a.count == 0
    assert a.mean() == 0.0
