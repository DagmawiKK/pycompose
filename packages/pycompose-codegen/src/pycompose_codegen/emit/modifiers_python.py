"""Python ``Modifier`` operations for every modifier the catalog declares.

``Modifier().padding(8)`` and ``Modifier().weight(1)`` append the wire
operation the host applies. The methods live on a generated base class
``Modifier`` inherits; the few conveniences a person designed (padding by side,
a square size) override them and call them.
"""

from __future__ import annotations

import json
from typing import Any

from pycompose_codegen.emit.literals import GENERATED_NOTICE
from pycompose_codegen.emit.overloads import python_name
from pycompose_codegen.emit.python_layout import docstring_arg

TYPES = {
    "number": "int | float",
    "integer": "int",
    "boolean": "bool",
    "string": "str",
    "actionId": "str | Intent | type[Intent]",
}


def _alias(name: str, prop: str) -> str:
    """The module-level ``Literal`` alias an enumerated prop is typed by."""
    return f"_{name[:1].upper()}{name[1:]}{prop[:1].upper()}{prop[1:]}"


def _parameter(name: str, prop: str, spec: dict[str, Any]) -> str:
    if spec["type"] == "enum":
        kind = _alias(name, prop)
    elif "valueType" in spec:
        kind = "JsonValue"
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
        # One prop is passed by position, as Compose's own call takes it.
        keyword = ["        *,"] if len(props) > 1 else []
        parameters += [*keyword, *(_parameter(name, p, props[p]) for p in optional)]
    if "scoped" in modifier:
        scopes = ", ".join(s["scope"].rsplit(".", 1)[-1] for s in modifier["scoped"])
        natives = ", ".join(sorted({s["native"] for s in modifier["scoped"]}))
        summary = [
            f'        """Native ``{natives}``.',
            "",
            f"        Worn inside {scopes}.",
        ]
    else:
        summary = [f'        """Native ``{modifier["call"]["function"]}``.']
    lines = [
        "    @_Operation",
        f"    def {python_name(name)}(",
        "        self,",
        *parameters,
        "    ) -> Modifier:",
        *summary,
        "",
    ]
    if props:
        lines.append("        Args:")
        for p in props:
            if p in required:
                note = "."
            elif "default" in props[p]:
                note = f"; {json.dumps(props[p]['default'])} unless given."
            else:
                note = ", omitted for its native default."
            lines += docstring_arg(python_name(p), f"Native {p}{note}")
        lines.append("")
    lines += ["        Returns:", "            A new modifier.", '        """']
    if not props:
        return [*lines, f'        return self._append("{name}")', ""]
    return [
        *lines,
        "        given: dict[str, JsonValue] = {",
        *(
            f'            "{p}": lower_action({python_name(p)}),'
            if props[p]["type"] == "actionId"
            else f'            "{p}": {python_name(p)},'
            for p in props
        ),
        "        }",
        "        return self._append(",
        f'            "{name}",',
        "            **{k: v for k, v in given.items() if v is not None},",
        "        )",
        "",
    ]


def render_operations(registry: dict[str, Any]) -> str:
    """Render ``pycompose/ui/generated_modifiers.py``.

    Args:
        registry: The catalog lock.

    Returns:
        The Python source.
    """
    operations = {
        name: modifier
        for name, modifier in sorted(registry.get("modifiers", {}).items())
        if "scoped" in modifier or "call" in modifier
    }
    aliases: list[str] = []
    methods: list[str] = []
    for name, modifier in operations.items():
        for prop, spec in modifier["props"].items():
            if spec["type"] == "enum":
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
                '"""Every modifier operation the catalog declares, as methods."""',
                "",
                "from __future__ import annotations",
                "",
                "from typing import TYPE_CHECKING, Literal",
                "",
                "from pycompose.app.intents import Intent, lower_action",
                "from pycompose.core.props import JsonValue",
                "from pycompose.ui.modifier_operation import _Operation",
                "",
                "if TYPE_CHECKING:",
                "    from pycompose.ui.modifiers import Modifier",
                "",
                *aliases,
                "",
                "",
                "class GeneratedOperations:",
                '    """Every catalog operation; Modifier inherits them."""',
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
