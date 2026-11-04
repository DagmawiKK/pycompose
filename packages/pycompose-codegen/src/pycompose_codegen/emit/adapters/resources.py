"""Props the host loads from the app's resources, in a native parameter's place.

``Text(resource="string:greeting")`` names text the host reads off the Compose
thread; it stands in for the ``text`` the call passes, which stays the fallback
while it loads or when it cannot. ``Image(resource=...)`` fills ``painter``,
which has no plain prop, so the image composes once its painter arrives. The
lock says which parameter a resource fills (``fills``) and which other props its
reader takes (``reads``); the readers are the host's ``resource<Kind>``.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.emit.adapters.fragments import Fragments
from pycompose_codegen.emit.adapters.policy import camel

__all__ = ["loaded_resources", "stand_in"]


def loaded_resources(
    props: dict[str, Any], out: Fragments
) -> dict[str, tuple[str, dict[str, Any]]]:
    """Read each resource prop through its host reader.

    Args:
        props: The component's declared props, by wire name.
        out: Collects the rendered pieces.

    Returns:
        Per native parameter filled: the resource prop and its spec.
    """
    fills: dict[str, tuple[str, dict[str, Any]]] = {}
    for prop, spec in props.items():
        if spec["type"] != "resource" or "fills" not in spec:
            continue
        native = spec["fills"]
        reads = ", ".join(
            f"model.props.{camel(name)}" for name in (prop, *spec.get("reads", ()))
        )
        out.locals.append(f"val {native}Resource = resources.{spec['decode']}({reads})")
        fills[native] = (prop, spec)
    return fills


def stand_in(fills: dict[str, tuple[str, dict[str, Any]]], out: Fragments) -> None:
    """Pass each loaded resource in its parameter's place.

    A parameter a plain prop also fills falls back to that prop's value; one
    only the resource fills waits for it, so the component composes once it
    has arrived.

    Args:
        fills: Per native parameter, the resource prop filling it.
        out: Collects the rendered pieces.
    """
    for native in fills:
        prefix = f"{native} = "
        for index, argument in enumerate(out.arguments):
            if argument.startswith(prefix):
                plain = argument.removeprefix(prefix)
                out.arguments[index] = f"{prefix}{native}Resource ?: {plain}"
                break
        else:
            out.arguments.append(f"{prefix}{native}Resource")
            out.gates.append(f"{native}Resource != null")
