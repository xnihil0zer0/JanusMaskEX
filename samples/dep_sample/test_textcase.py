"""Behavioral spec for the dep_sample textcase module (run inside the replicant venv)."""

from textcase import pluralize_word, to_snake, to_camel, to_dashed


def test_pluralize_word():
    assert pluralize_word('post') == 'posts'
    assert pluralize_word('category') == 'categories'


def test_to_snake():
    assert to_snake('DeviceType') == 'device_type'


def test_to_camel():
    assert to_camel('device_type') == 'DeviceType'


def test_to_dashed():
    assert to_dashed('foo_bar') == 'foo-bar'
