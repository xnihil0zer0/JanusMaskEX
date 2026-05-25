from geopack.base import unit_length, double_area


def test_unit_length():
    assert unit_length() == 1


def test_double_area():
    assert double_area(3) == 18
    assert double_area(0) == 0
