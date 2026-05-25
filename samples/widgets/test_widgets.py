"""Behavioral spec for samples/widgets -- the rebuild engine copies this verbatim."""

from __future__ import annotations

from widgets import Accumulator, double, file_size, quadruple


def test_double():
    assert double(3) == 6
    assert double(-2) == -4
    assert double(0) == 0


def test_quadruple():
    assert quadruple(3) == 12
    assert quadruple(-1) == -4
    assert quadruple(0) == 0


def test_file_size(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello", encoding="utf-8")
    assert file_size(str(f)) == 5
    assert file_size(str(tmp_path / "missing.txt")) == -1


def test_accumulator():
    acc = Accumulator()
    assert acc.add(3) == 3
    assert acc.add(4) == 7
    acc.reset()
    assert acc.add(1) == 1


def test_accumulator_start():
    acc = Accumulator(10)
    assert acc.add(5) == 15
