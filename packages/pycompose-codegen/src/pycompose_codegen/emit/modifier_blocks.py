"""Kotlin for the modifier operations whose call defers its props to a block.

``graphicsLayer`` sets members while Compose draws; ``offset`` asks a lambda
where the node goes while Compose lays it out. A bound prop is read inside
those blocks, so a frame of animation invalidates that phase alone -- never the
composition. Everything the block reads is declared before it, because the
resolvers and the binding states are composable and the block is not.
"""

from __future__ import annotations

from typing import Any, cast

from pycompose.model.programs.bindings import animatable
from pycompose_codegen.emit.literals import kotlin_string
from pycompose_codegen.emit.modifier_bindings import animated, deferred
from pycompose_codegen.emit.modifier_values import converter, fallback, prop_value


def _values(
    modifier: dict[str, Any],
    converters: dict[str, dict[str, Any]],
) -> list[str]:
    """The values a block reads, declared before it.

    A block Compose invokes per frame keeps a state and reads it inside, so a
    frame of animation invalidates that phase alone. A block it invokes at some
    other time -- ``semantics`` collects what the node means -- is read in the
    composition instead: a bound prop there recomposes, as any prop does.
    """
    call = modifier["call"]
    block = call.get("block", {})
    arguments = call.get("arguments") or block["result"]["arguments"]
    lines: list[str] = []
    for prop, argument in arguments.items():
        spec = modifier["props"][prop]
        if argument.get("member") == "function" or "constants" in argument:
            continue
        if animatable(spec) and call["phase"] != "composition":
            lines += deferred(
                prop,
                converter(spec, converters),
                f'op["{prop}"]',
                prop_value(spec, cast("str", spec["animation"])),
                call["phase"],
                pure="valueType" not in spec,
            )
            continue
        if animatable(spec):
            native = cast("str", spec["animation"])
            plain = prop_value(spec, native)
            read = animated(converter(spec, converters), "wire", plain)
            bound = "wire"
        else:
            read = prop_value(spec, argument["type"])
            bound = "value"
        head = f'                val {prop}Value = op["{prop}"]?.let {{ {bound} -> '
        lines.append(f"{head}{read} }}")
    return lines


def _held(prop: str, spec: dict[str, Any], native: str) -> str:
    """What a deferred block reads for a prop: its state, or the pin's default."""
    if spec.get("required"):
        return f"{prop}State!!.value"
    return f"{prop}State?.value ?: {fallback(prop, spec, native)}"


def block(
    name: str,
    modifier: dict[str, Any],
    function: str,
    converters: dict[str, dict[str, Any]],
) -> list[str]:
    """The branch of an operation whose call sets members of a receiver block."""
    call = modifier["call"]
    lines = [f"            {kotlin_string(name)} -> {{", *_values(modifier, converters)]
    parameter = call["block"]["parameter"]
    lines.append(f"                Modifier.{function}({parameter} = {{")
    for prop, argument in call["arguments"].items():
        spec = modifier["props"][prop]
        member = argument["source"]["name"]
        if argument["member"] == "function":
            flag = f'op["{prop}"]?.jsonPrimitive?.booleanOrNull == true'
            lines.append(f"                    if ({flag}) {member}()")
            continue
        if "constants" in argument:
            owner = argument["type"]
            lines += [
                f'                    op["{prop}"]?.let {{',
                f"                        {member} =",
                "                            when (it.jsonPrimitive.content) {",
                *(
                    f"                                {kotlin_string(value)} -> "
                    f"{owner}.{constant}"
                    for value, constant in argument["constants"].items()
                ),
                f'                                else -> error("unknown {prop}")',
                "                            }",
                "                    }",
            ]
            continue
        if animatable(spec) and call["phase"] != "composition":
            lines.append(
                f"                    {member} = {_held(prop, spec, argument['type'])}"
            )
            continue
        lines.append(f"                    {prop}Value?.let {{ {member} = it }}")
    return [*lines, "                })", "            }"]


def result(
    name: str,
    modifier: dict[str, Any],
    function: str,
    converters: dict[str, dict[str, Any]],
) -> list[str]:
    """The branch of an operation whose block answers where the node goes.

    The pin's own function builds that answer from the props, and a prop of
    another type converts through a member of the block's receiver.
    """
    call = modifier["call"]
    block = call["block"]
    factory = block["result"]
    lines = [f"            {kotlin_string(name)} -> {{", *_values(modifier, converters)]
    arguments = []
    for prop, argument in factory["arguments"].items():
        spec = modifier["props"][prop]
        value = _held(prop, spec, argument["type"])
        if "convert" in argument:
            value = f"({value}).{argument['convert']}()"
        arguments.append(f"{argument['parameter']} = {value}")
    lines += [
        f"                Modifier.{function}({block['parameter']} = {{",
        f"                    {factory['function'].rsplit('.', 1)[-1]}(",
        *(f"                        {argument}," for argument in arguments),
        "                    )",
        "                })",
        "            }",
    ]
    return lines
