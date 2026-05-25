"""A module backed by the third-party ``inflection`` dependency."""
import inflection


def camelize_label(text: str) -> str:
    """Return the CamelCase form of an underscored ``text`` label."""
    return inflection.camelize(text)
