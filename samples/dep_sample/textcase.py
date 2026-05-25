"""Tiny text-case helpers built on the third-party `inflection` PyPI package.

This is a C9.7 environment-faithful rebuild sample: every function depends on an
EXTERNAL dependency (`inflection`), so a faithful replicant must provision its
own `.venv`, install `inflection`, and verify inside that venv. The module
imports the dependency at top level, which is why the parent-python oracle is
unavailable for these units (they route to the venv-tests-only path).
"""

import inflection


def pluralize_word(word):
    """Return the English plural of ``word`` (e.g. 'post' -> 'posts')."""
    return inflection.pluralize(word)


def to_snake(name):
    """Convert a CamelCase ``name`` to snake_case (e.g. 'DeviceType' -> 'device_type')."""
    return inflection.underscore(name)


def to_camel(name):
    """Convert a snake_case ``name`` to CamelCase (e.g. 'device_type' -> 'DeviceType')."""
    return inflection.camelize(name)


def to_dashed(name):
    """Replace underscores with dashes in ``name`` (e.g. 'foo_bar' -> 'foo-bar')."""
    return inflection.dasherize(name)
