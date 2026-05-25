from geopack.shapes import square_area


def test_square_area():
    assert square_area(4) == 16
    assert square_area(0) == 0
    assert square_area(1) == 1
