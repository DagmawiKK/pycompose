"""Values a component takes that the pin builds from what the app can state.

``TooltipBox(positionProvider: PopupPositionProvider)`` takes a type no value
family carries: the provider measures the anchor and the window, which the app
cannot. The pin offers one composable that builds it,
``TooltipDefaults.rememberTooltipPositionProvider(positioning: TooltipAnchorPosition)``,
from a value the wire does carry. Wherever a type has exactly one such public
builder, the parameter is built: the builder's required parameters become the
component's props, and the host calls the builder with them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory, Parameter


def value_builders(
    found: Inventory, defaults: dict[tuple[str, str, str], dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Every type with one public composable building it, by slash classifier.

    Args:
        found: The pinned inventory.
        defaults: Compiler-resolved defaults by JVM identity.

    Returns:
        Per type: its builder's dotted name, required parameters and defaults.
    """
    candidates: dict[str, list[Any]] = {}
    for d in found.declarations:
        if (
            d.composable
            and d.document.get("declarationKind") == "function"
            and d.document.get("visibility") == "PUBLIC"
            and "kotlin/Deprecated" not in d.annotations
            and d.receiver is None
            and (d.dispatch_receiver is None or d.document.get("classKind") == "OBJECT")
            and not d.return_type.nullable
            and not d.return_type.arguments
            and d.return_type.classifier != "kotlin/Unit"
        ):
            candidates.setdefault(d.return_type.classifier, []).append(d)
    builders = {}
    for classifier, made in candidates.items():
        if len(made) != 1:
            continue
        builder = made[0]
        holder = builder.owner if builder.dispatch_receiver else builder.package
        builders[classifier] = {
            "kind": "built",
            "factory": f"{holder.replace('$', '.')}.{builder.name}",
            "parameters": [p for p in builder.parameters if p.required],
            "defaults": defaults.get(
                (builder.owner, builder.jvm_name or "", builder.jvm_descriptor or ""),
                {},
            ),
        }
    return builders


def built_rule(
    builder: dict[str, Any],
    bind: Callable[[Parameter, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """A built parameter's rule: its builder, and how each argument reaches the wire.

    Args:
        builder: The type's builder (``value_builders``).
        bind: Binds one of the builder's parameters, given the builder's defaults.

    Returns:
        The rule, each required argument bound as a component parameter would be.
    """
    return {
        "policy": "built",
        "factory": builder["factory"],
        "arguments": {
            # Spelled as a plan's parameter is, so each shapes into a prop the same way.
            parameter.name: {
                **bind(parameter, builder["defaults"]),
                "type": parameter.type.document,
                "required": parameter.required,
                "hasDefault": parameter.has_default,
            }
            for parameter in builder["parameters"]
        },
    }


def buildable(parameter: Parameter, holders: dict[str, dict[str, Any]]) -> bool:
    """Whether to build a parameter: the builder carries something from the app,
    or the parameter has no default to fall back on.

    Args:
        parameter: The component's parameter.
        holders: Holders and builders by slash classifier.

    Returns:
        True when the parameter is built.
    """
    built = holders.get(parameter.type.classifier, {})
    return (
        built.get("kind") == "built"
        and not parameter.type.nullable
        and (bool(built["parameters"]) or not parameter.has_default)
    )
