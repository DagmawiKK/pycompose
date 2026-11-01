"""Kotlin for every modifier operation: ``GeneratedModifiers.apply``.

An operation policy declares calls the ``Modifier`` extension the pin resolved
it to (its ``call``). A call that defers its props to a block is rendered in
:mod:`.modifier_blocks`; every other is one call with named arguments. An
operation a composition scope declares (``RowScope.weight``) applies on the
receiver its node's parent lambda carries: the generated code matches the
receiver against the scopes declaring it and calls the member there, or returns
null when the node is not inside any of them, which the renderer reports.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.literals import GENERATED_NOTICE, kotlin_string
from pycompose_codegen.emit.modifier_blocks import block, result
from pycompose_codegen.emit.modifier_values import argument as _argument
from pycompose_codegen.emit.modifier_values import passed
from pycompose_codegen.emit.rules import die


def _direct(
    name: str,
    modifier: dict[str, Any],
    converters: dict[str, dict[str, Any]],
) -> list[str]:
    """The branch of one operation that calls its resolved function."""
    call = modifier["call"]
    function = call["function"].rsplit(".", 1)[-1]
    if "block" in call:
        if "result" in call["block"]:
            return result(name, modifier, function, converters)
        return block(name, modifier, function, converters)
    arguments = [
        f"{argument['parameter']} = "
        f"{passed(prop, modifier['props'][prop], argument, converters)}"
        for prop, argument in call["arguments"].items()
    ]
    bare = call.get("bare", {})
    indent = " " * (20 if bare else 16)
    tagged = [
        f"Modifier.{function}(",
        *(f"{indent}    {argument}," for argument in arguments),
        f"{indent})",
    ]
    if not bare:
        return [
            f"            {kotlin_string(name)} ->",
            f"                {tagged[0]}",
            *tagged[1:],
        ]
    if len(bare) > 1:
        die(f"modifier {name!r}: one prop at most may ride the wire bare")
    ((prop, overload),) = bare.items()
    # The bare number calls the overload that takes exactly that Dp.
    return [
        f"            {kotlin_string(name)} ->",
        f'                if (op.getValue("{prop}") is JsonObject) {{',
        f"                    {tagged[0]}",
        *tagged[1:],
        "                } else {",
        f"                    Modifier.{function}({overload['parameter']} = "
        "com.pycompose.renderer.PropResolver"
        f'.dp(op.getValue("{prop}").jsonPrimitive.double).getOrThrow())',
        "                }",
    ]


def _imports(registry: dict[str, Any]) -> list[str]:
    """What the direct calls name unqualified: their functions and members."""
    names: set[str] = set()
    for modifier in registry.get("modifiers", {}).values():
        call = modifier.get("call")
        if call is None:
            continue
        names.add(call["function"])
        # A rendered default such as ``(0).dp`` calls the dp extension property.
        if any(
            str(spec.get("nativeDefault", "")).endswith(".dp")
            for spec in modifier.get("props", {}).values()
        ):
            names.add("androidx.compose.ui.unit.dp")
        deferred = call.get("block")
        if deferred is not None and "result" in deferred:
            # The block answers with a value the pin's own function builds.
            names.add(deferred["result"]["function"])
        elif deferred is not None:
            # A member of the receiver needs no import; an extension on it does,
            # and the pin states which file declares it.
            names.update(
                f"{argument['source']['owner'].rsplit('.', 1)[0]}"
                f".{argument['source']['name']}"
                for argument in call["arguments"].values()
                if argument["source"]["owner"] != deferred["receiver"]
            )
    converters = registry.get("converters", {})
    for modifier in registry.get("modifiers", {}).values():
        for spec in modifier.get("props", {}).values():
            entry = converters.get(spec.get("animation"))
            if entry is not None:
                names.update(entry["imports"])
    return [f"import {name}" for name in sorted(names)]


def render_modifiers(registry: dict[str, Any]) -> str:
    """Render ``GeneratedModifiers.kt``.

    Args:
        registry: The catalog lock.

    Returns:
        The Kotlin source.
    """
    modifiers = registry.get("modifiers", {})
    scoped = {
        name: modifier
        for name, modifier in sorted(modifiers.items())
        if "scoped" in modifier
    }
    converters = registry.get("converters", {})
    direct = [
        line
        for name, modifier in sorted(modifiers.items())
        if "call" in modifier
        for line in _direct(name, modifier, converters)
    ]
    markers = sorted(
        {
            m
            for modifier in scoped.values()
            for s in modifier["scoped"]
            for m in s.get("optIn", ())
        }
    )
    branches = []
    for name, modifier in scoped.items():
        branches += [
            f"            {kotlin_string(name)} ->",
            "                when (scope) {",
        ]
        for declaration in modifier["scoped"]:
            renamed = declaration.get("parameters", {})
            branches += [
                f"                    is {declaration['scope']} ->",
                "                        with(scope) {",
                f"                            Modifier.{declaration['native']}(",
                *(
                    f"                                "
                    f"{_argument(prop, spec, renamed.get(prop, prop), converters)},"
                    for prop, spec in modifier["props"].items()
                ),
                "                            )",
                "                        }",
            ]
        branches += ["                    else -> null", "                }"]
    header = [f"// {GENERATED_NOTICE}"]
    if markers:
        header.append("@file:OptIn(" + ", ".join(f"{m}::class" for m in markers) + ")")
    return "\n".join(
        [
            *header,
            "package com.pycompose.renderer.generated",
            "",
            "import androidx.compose.runtime.Composable",
            "import androidx.compose.ui.Modifier",
            *_imports(registry),
            "import kotlinx.serialization.json.JsonObject",
            "import kotlinx.serialization.json.boolean",
            "import kotlinx.serialization.json.booleanOrNull",
            "import kotlinx.serialization.json.double",
            "import kotlinx.serialization.json.jsonPrimitive",
            "import kotlinx.serialization.json.long",
            "",
            "/** Every modifier operation the catalog declares, from its wire form. */",
            "object GeneratedModifiers {",
            "    /**",
            "     * [type] applied with [op]'s props; null for an operation worn",
            "     * outside every scope declaring it. [dispatch] sends a click's id.",
            "     */",
            "    @Composable",
            "    fun apply(",
            "        type: String,",
            "        scope: Any?,",
            "        op: JsonObject,",
            "        dispatch: (String) -> Unit,",
            "    ): Modifier? =",
            "        when (type) {",
            *direct,
            *branches,
            "            else -> null",
            "        }",
            "}",
            "",
        ]
    )
