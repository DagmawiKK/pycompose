"""Render the closed, compiler-resolved default-expression vocabulary.

This is not a Kotlin expression escape hatch. Unknown syntax fails generation;
contextual properties/calls stay native and are evaluated during composition.
"""

from __future__ import annotations

import math
import re
from typing import Any

SYMBOL = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")


def render_default(expression: dict[str, Any], imports: set[str]) -> str:
    """Validate and render one typed expression, collecting extension imports.

    The vocabulary is closed and mirrors the dev-only tool in ``android/tools/``:
    literals, public properties, singleton objects, extension properties over a
    literal receiver, public member reads on an already-representable receiver,
    and zero-argument public calls. A call carrying arguments would smuggle
    per-binding Kotlin back into the schema, so it is refused rather than rendered.

    Args:
        expression: Compiler-resolved default evidence.
        imports: Collects aliased imports the rendered code needs.

    Returns:
        Kotlin source for one default value.

    Raises:
        ValueError: The evidence is outside the closed vocabulary.
    """
    kind = expression.get("kind")
    if kind == "literal":
        _keys(expression, {"kind", "type", "value"})
        return _literal(expression["value"], expression["type"])
    if kind in {"property", "object", "extensionProperty", "memberProperty", "call"}:
        fields = {
            "property": set(),
            "object": set(),
            "extensionProperty": {"receiver"},
            "memberProperty": {"receiver"},
            "call": set(),
        }[kind]
        _keys(expression, {"kind", "symbol", *fields})
        symbol = expression["symbol"]
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            raise ValueError("default needs a qualified native symbol")
        if kind in {"property", "object"}:
            return symbol
        if kind == "extensionProperty":
            alias = "default_" + symbol.replace(".", "_")
            imports.add(f"import {symbol} as {alias}")
            return f"({render_default(expression['receiver'], imports)}).{alias}"
        if kind == "memberProperty":
            member = symbol.rsplit(".", 1)[1]
            return f"({render_default(expression['receiver'], imports)}).{member}"
        return f"{symbol}()"
    raise ValueError(f"unsupported native default: {kind}")


def _keys(expression: dict[str, Any], expected: set[str]) -> None:
    if set(expression) != expected:
        raise ValueError("invalid native default fields")


def _literal(value: Any, classifier: str) -> str:
    """Render a literal of the declared type, or refuse. Never widen or narrow types."""
    from pycompose.schema.codegen.literals import kotlin_string

    if value is None:
        return "null"
    if classifier == "kotlin/Boolean":
        if isinstance(value, bool):
            return "true" if value else "false"
    elif classifier == "kotlin/String":
        if isinstance(value, str):
            return kotlin_string(value)
    elif classifier in {"kotlin/Int", "kotlin/Long"}:
        bits = 32 if classifier == "kotlin/Int" else 64
        if type(value) is int and -(2 ** (bits - 1)) <= value < 2 ** (bits - 1):
            if value == -(2**63):
                return "Long.MIN_VALUE"
            return str(value) + ("L" if bits == 64 else "")
    elif (
        classifier in {"kotlin/Float", "kotlin/Double"}
        and type(value)
        in {
            int,
            float,
        }
        and math.isfinite(value)
    ):
        return repr(float(value)) + ("f" if classifier == "kotlin/Float" else "")
    raise ValueError(f"invalid native literal: {classifier}")
