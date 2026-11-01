"""Kotlin for an implementation family: an object whose methods run host programs."""

from __future__ import annotations

from typing import Any

# A host function's arguments travel as Long, Double and Boolean.
_ARGUMENT = {"Int": ".toLong()", "Float": ".toDouble()"}
_RESULT = {
    "Int": "(it as Long).toInt()",
    "Long": "it as Long",
    "Float": "(it as Double).toFloat()",
    "Double": "it as Double",
    "Boolean": "it as Boolean",
}


def implementation(spec: dict[str, Any]) -> list[str]:
    """An object implementing the interface, each method calling its program.

    A method the app left unset keeps the interface's own body.

    Args:
        spec: An ``implementation`` family's descriptor.

    Returns:
        The Kotlin lines of the resolver's branch body.
    """
    lines = [f"                object : {spec['native']['implements']} {{"]
    for field, rule in spec["parameters"].items():
        native = rule["native"]
        params = ", ".join(f"{p['name']}: {p['type']}" for p in native["parameters"])
        args = ", ".join(
            p["name"] + _ARGUMENT.get(p["type"], "") for p in native["parameters"]
        )
        names = ", ".join(p["name"] for p in native["parameters"])
        result = _RESULT[native["result"]]
        lines.append(
            f"                    override fun {field}({params}): {native['result']} ="
        )
        if rule.get("required"):
            lines.append(
                f"                        value.{field}.call({args}).let {{ {result} }}"
            )
        else:
            call = f"value.{field}?.call({args})?.let {{ {result} }}"
            lines += [
                f"                        {call}",
                f"                            ?: super.{field}({names})",
            ]
    lines.append("                }")
    return lines
