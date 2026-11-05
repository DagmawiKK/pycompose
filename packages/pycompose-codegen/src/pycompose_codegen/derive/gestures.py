"""Gestures: the pin's detectors, each a modifier the host runs in ``pointerInput``.

``Modifier.pointerInput(key) { ... }`` hands its block a ``PointerInputScope``,
and the pin's gesture detectors are that scope's public suspending extensions
(``detectTapGestures``, ``detectDragGestures``, ...). Each detector whose
callbacks all have a protocol becomes one modifier, named after it, whose call
runs the detector inside ``pointerInput``. A callback is one of two things,
read from its type:

* an event -- no argument, or one ``Offset`` -- which dispatches the action
  the app binds, an ``Offset`` as the payload's ``x`` and ``y`` in dp;
* the detector's one continuous callback, the one it cannot do without, which
  takes the ``PointerInputChange`` first: it runs every frame of the gesture,
  so it never reaches Python. Its other arguments are deltas, which the host
  adds, in dp, into streams named after the callback (``onDrag`` gives
  ``dragX`` and ``dragY``) for expressions to follow.

An optional callback of any other shape is left out; a detector with a required
one is refused, with its reason. Of a detector's overloads the one with every
parameter placed stands.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Declaration, Inventory
from pycompose_codegen.derive.classpath_types import KotlinType

SCOPE = "androidx/compose/ui/input/pointer/PointerInputScope"
CHANGE = "androidx/compose/ui/input/pointer/PointerInputChange"
OFFSET = "androidx/compose/ui/geometry/Offset"
FLOAT = "kotlin/Float"
UNIT = "kotlin/Unit"


class NoProtocolError(Exception):
    """A detector or callback that has no protocol, with why."""


def gestures(found: Inventory) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Every gesture detector the pin declares, as modifiers, and those refused.

    Args:
        found: The pinned inventory.

    Returns:
        The modifiers by detector name, and each refused detector with why.
    """
    placed: dict[str, dict[str, Any]] = {}
    refused: dict[str, str] = {}
    for declaration in found.declarations:
        receiver = declaration.receiver
        if (
            receiver is None
            or receiver.classifier != SCOPE
            or declaration.disposition not in {"ui", "support"}
            or not declaration.document.get("suspend")
            or declaration.return_type.classifier != UNIT
        ):
            continue
        try:
            modifier = _modifier(declaration)
        except NoProtocolError as why:
            refused.setdefault(declaration.name, str(why))
            continue
        # Of two placeable overloads, the one with more callbacks offers more.
        held = placed.get(declaration.name)
        if held is None or len(modifier["props"]) > len(held["props"]):
            placed[declaration.name] = modifier
            refused.pop(declaration.name, None)
    return dict(sorted(placed.items())), refused


def _modifier(declaration: Declaration) -> dict[str, Any]:
    props: dict[str, Any] = {}
    events: dict[str, dict[str, Any]] = {}
    continuous: dict[str, Any] | None = None
    for parameter in declaration.parameters:
        value = parameter.type
        arguments = _function(value)
        if arguments is not None and arguments[:1] == [CHANGE] and parameter.required:
            continuous = {
                "callback": parameter.name,
                "streams": _streams(parameter.name, arguments[1:]),
            }
        elif arguments is not None and arguments in ([], [OFFSET]):
            axes = ["x", "y"] if arguments else []
            payload = [{"name": axis, "type": "number"} for axis in axes]
            props[parameter.name] = {
                "type": "actionId",
                **({"payload": payload} if payload else {}),
            }
            events[parameter.name] = {"payload": axes, "nullable": value.nullable}
        elif parameter.required:
            raise NoProtocolError(
                f"{parameter.name}: no gesture protocol for {value.classifier}"
            )
    if continuous is None and not events:
        raise NoProtocolError("no callback a gesture can state")
    return {
        "props": props,
        "gesture": {
            "detector": f"{declaration.package}.{declaration.name}",
            "events": events,
            **({"continuous": continuous} if continuous else {}),
        },
    }


def _function(value: KotlinType) -> list[str] | None:
    """A synchronous Unit callback's argument types, or None for anything else."""
    if not value.classifier.startswith("kotlin/Function") or value.suspend:
        return None
    types = [t for _, t in value.arguments]
    if not types or any(t is None for t in types) or types[-1].classifier != UNIT:  # type: ignore[union-attr]
        return None
    return [t.classifier for t in types[:-1]]  # type: ignore[union-attr]


def _streams(callback: str, deltas: list[str]) -> list[dict[str, Any]]:
    """The streams a continuous callback's deltas add into, named after it."""
    base = callback.removeprefix("on")
    base = base[:1].lower() + base[1:]
    streams = []
    for index, delta in enumerate(deltas, start=1):
        if delta == OFFSET:
            streams += [
                {"name": f"{base}X", "argument": index, "axis": "x"},
                {"name": f"{base}Y", "argument": index, "axis": "y"},
            ]
        elif delta == FLOAT:
            streams.append({"name": base, "argument": index})
        else:
            raise NoProtocolError(f"{callback}: a delta of {delta} does not add")
    if not streams:
        raise NoProtocolError(f"{callback}: no delta to follow")
    return streams
