"""How a generated adapter spells the wire in Kotlin.

The tables are the embedding policy every adapter follows: which Kotlin type a
wire type becomes, which types render with no decision, and which numeric
conversions a provider may make.
"""

from __future__ import annotations

SCALAR_KOTLIN = {
    "string": "String",
    "boolean": "Boolean",
    "integer": "Long",
    "number": "Double",
}


MECHANICAL = {"string", "boolean", "integer", "number", "actionId", "modifier"}
"""Schema prop types an adapter can render with no decision.

A colour or a named constant renders through its value family's resolver; a
resource only through a wrapper, which loads it off the Compose thread.
"""


NUMERIC_KOTLIN = frozenset({"Byte", "Short", "Int", "Long", "Float", "Double"})
"""Kotlin's numeric primitives: the only types a provider coerces between."""


NUMERIC_CONVERSIONS = {
    ("Double", "Float"): "toFloat",
    ("Double", "Int"): "toInt",
    ("Double", "Long"): "toLong",
    ("Float", "Double"): "toDouble",
    ("Int", "Float"): "toFloat",
    ("Int", "Long"): "toLong",
    ("Long", "Double"): "toDouble",
    ("Long", "Float"): "toFloat",
    ("Long", "Int"): "toInt",
}
"""Each entry is Kotlin's own named conversion; an unlisted pair is refused."""


def camel(name: str) -> str:
    """Return a snake_case wire name as camelCase.

    Args:
        name: The schema's prop name.

    Returns:
        The Kotlin property name.
    """
    head, *rest = name.split("_")
    return head + "".join(pascal(word) for word in rest)


def pascal(name: str) -> str:
    """Return a name with its first letter capitalised, the rest as written."""
    return name[:1].upper() + name[1:]


def simple(scope: str) -> str:
    """A scope's class as the adapters spell it: imported, so by simple name."""
    return scope.rsplit(".", 1)[-1]
