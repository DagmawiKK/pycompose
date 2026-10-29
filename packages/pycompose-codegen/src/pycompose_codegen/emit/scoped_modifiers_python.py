"""Python ``Modifier`` operations for the modifiers composition scopes declare.

``Modifier().weight(1)`` appends the wire operation the host applies on the
receiver of the node's parent lambda; the methods live on a generated base
class ``Modifier`` inherits, so the hand-written operations stay apart.
"""

from __future__ import annotations

import json
from typing import Any

from pycompose_codegen.emit.literals import GENERATED_NOTICE
from pycompose_codegen.emit.overloads import python_name

TYPES = {
    "number": "int | float",
    "integer": "int",
    "boolean": "bool",
    "string": "str",
}


def _alias(name: str, prop: str) -> str:
    """The module-level ``Literal`` alias an enumerated prop is typed by."""
    return f"_{name[:1].upper()}{name[1:]}{prop[:1].upper()}{prop[1:]}"


def _parameter(name: str, prop: str, spec: dict[str, Any]) -> str:
    if "valueType" in spec:
        kind = "JsonValue"
    elif spec["type"] == "enum":
        kind = _alias(name, prop)
    else:
        kind = TYPES[spec["type"]]
    if spec.get("required"):
        return f"        {python_name(prop)}: {kind},"
    if "default" in spec:
        default = spec["default"]
        literal = json.dumps(default) if isinstance(default, str) else repr(default)
        return f"        {python_name(prop)}: {kind} = {literal},"
    return f"        {python_name(prop)}: {kind} | None = None,"


def _method(name: str, modifier: dict[str, Any]) -> list[str]:
    props = modifier["props"]
    required = [p for p, s in props.items() if s.get("required")]
    optional = [p for p in props if p not in required]
    parameters = [_parameter(name, p, props[p]) for p in required]
    if optional:
        parameters += ["        *,", *(_parameter(name, p, props[p]) for p in optional)]
    scopes = ", ".join(s["scope"].rsplit(".", 1)[-1] for s in modifier["scoped"])
    natives = ", ".join(sorted({s["native"] for s in modifier["scoped"]}))
    lines = [
        "    @_Operation",
        f"    def {python_name(name)}(",
        "        self,",
        *parameters,
        "    ) -> Modifier:",
        f'        """Native ``{natives}``.',
        "",
        f"        Worn inside {scopes}.",
        "",
    ]
    if props:
        lines.append("        Args:")
        lines += [
            f"            {python_name(p)}: Native {p}"
            + ("." if p in required else ", omitted for its native default.")
            for p in props
        ]
        lines.append("")
    lines += ["        Returns:", "            A new modifier.", '        """']
    if not props:
        return [*lines, f'        return self._append("{name}")', ""]
    return [
        *lines,
        "        given: dict[str, JsonValue] = {",
        *(f'            "{p}": {python_name(p)},' for p in props),
        "        }",
        "        return self._append(",
        f'            "{name}",',
        "            **{k: v for k, v in given.items() if v is not None},",
        "        )",
        "",
    ]


def render_scoped_operations(registry: dict[str, Any]) -> str:
    """Render ``pycompose/ui/scoped_modifiers.py``.

    Args:
        registry: The catalog lock.

    Returns:
        The Python source.
    """
    scoped = {
        name: modifier
        for name, modifier in sorted(registry.get("modifiers", {}).items())
        if "scoped" in modifier
    }
    aliases: list[str] = []
    methods: list[str] = []
    for name, modifier in scoped.items():
        for prop, spec in modifier["props"].items():
            if spec["type"] == "enum" and "valueType" not in spec:
                aliases += [
                    f"{_alias(name, prop)} = Literal[",
                    *(f"    {json.dumps(v)}," for v in spec["values"]),
                    "]",
                ]
        methods += _method(name, modifier)
    return (
        "\n".join(
            [
                f"# {GENERATED_NOTICE}",
                '"""Modifier operations composition scopes declare (``weight``)."""',
                "",
                "from __future__ import annotations",
                "",
                "from typing import TYPE_CHECKING, Literal",
                "",
                "from pycompose.core.props import JsonValue",
                "from pycompose.ui.modifier_operation import _Operation",
                "",
                "if TYPE_CHECKING:",
                "    from pycompose.ui.modifiers import Modifier",
                "",
                *aliases,
                "",
                "",
                "class ScopedOperations:",
                '    """Operations worn only inside a parent declaring them."""',
                "",
                "    __slots__ = ()",
                "",
                "    def _append(self, name: str, **props: JsonValue) -> Modifier:",
                "        raise NotImplementedError",
                "",
                *methods,
            ]
        ).rstrip()
        + "\n"
    )
