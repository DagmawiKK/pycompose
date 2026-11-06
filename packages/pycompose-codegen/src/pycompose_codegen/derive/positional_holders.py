"""State holders whose family the pin implies: one scrollable position.

``HorizontalPager(state: PagerState)`` scrolls through pages; Python wants to
say which page and hear the page it settles on. That is the whole family
whenever a holder states it in its types:

* it is a ``ScrollableState``, so it is at rest once it stops scrolling;
* its drive is the public suspend member taking just an ``Int``, the
  ``animate...`` one where several do, as Compose spells an animated change;
* its position is the ``Int`` property the drive's parameter names: exactly
  (``ScrollState.value``), or ending a property its constructor also takes
  (``animateScrollToPage(page)`` and ``PagerState(currentPage)``);
* its ``remember...`` factory takes an ``Int`` it starts at, and a count
  (``() -> Int``) where it has one, which the host fills with the children;
  of several, the one needing no opt-in.

Where its drive takes an ``AnimationSpec`` and it has the other member, the
one that moves without animating (``scrollToPage`` beside
``animateScrollToPage``), the app may bind the position: ``animate`` travels
through the drive with its spec, ``follow`` tracks through the other.

The host's one positional runtime drives every such holder. A holder the types
leave ambiguous is not one.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory
from pycompose_codegen.derive.classpath_types import Declaration
from pycompose_codegen.derive.opt_ins import OptInIndex, opt_in_index, required_opt_ins

SCROLLABLE = "androidx/compose/foundation/gestures/ScrollableState"
INT = "kotlin/Int"
COUNT = "kotlin/Function0"
SPEC = "androidx/compose/animation/core/AnimationSpec"


def positional_holders(found: Inventory) -> dict[str, dict[str, Any]]:
    """Every holder class with one scrollable position, by slash classifier.

    Args:
        found: The pinned inventory.

    Returns:
        Per holder: its class, factory, the factory's start and count
        parameters, its position property and its drive, and where it can
        travel, the drive's spec parameter and the member that snaps.
    """
    members: dict[str, list[Declaration]] = {}
    for declaration in found.declarations:
        owner = declaration.owner.replace(".", "/")
        if _public(declaration):
            members.setdefault(owner, []).append(declaration)
    index = opt_in_index(found)
    holders = {}
    for classifier, own in sorted(members.items()):
        supertypes = own[0].document.get("classSupertypes") or []
        if SCROLLABLE not in {t.get("classifier") for t in supertypes}:
            continue
        drives = _drives(own)
        drive = _drive(drives)
        position = _position(own, drive) if drive is not None else None
        factory = _factory(found, classifier, index)
        if position is None or drive is None or factory is None:
            continue
        start = next(p for p in factory.parameters if p.type.classifier == INT)
        count = [p for p in factory.parameters if _count(p.type)]
        holders[classifier] = {
            "holder": classifier.replace("/", "."),
            "factory": f"{factory.package}.{factory.name}",
            "initial": start.name,
            **({"count": count[0].name} if count else {}),
            "position": position,
            "drive": drive.name,
            **_travel(drives, drive),
        }
    return holders


def _public(declaration: Declaration) -> bool:
    return (
        declaration.document.get("visibility") == "PUBLIC"
        and "kotlin/Deprecated" not in declaration.annotations
    )


def _position(own: list[Declaration], drive: Declaration) -> str | None:
    """The ``Int`` property the drive's parameter names; one, or none."""
    named = next(p.name for p in drive.parameters if p.required)
    properties = {
        d.name
        for d in own
        if d.document.get("declarationKind") == "property"
        and d.return_type.classifier == INT
        and not d.return_type.nullable
    }
    if named in properties:
        return named
    taken = {
        p.name
        for d in own
        if d.document.get("declarationKind") == "constructor"
        for p in d.parameters
        if p.type.classifier == INT
    }
    suffix = named[:1].upper() + named[1:]
    found = [name for name in properties & taken if name.endswith(suffix)]
    return found[0] if len(found) == 1 else None


def _drives(own: list[Declaration]) -> list[Declaration]:
    """The suspend members taking just a position."""
    return [
        d
        for d in own
        if d.document.get("declarationKind") == "function"
        and d.document.get("suspend")
        and [p.type.classifier for p in d.parameters if p.required] == [INT]
    ]


def _drive(drives: list[Declaration]) -> Declaration | None:
    """The drive, the animating one of several."""
    if len(drives) > 1:
        drives = [d for d in drives if d.name.startswith("animate")]
    return drives[0] if len(drives) == 1 else None


def _travel(drives: list[Declaration], drive: Declaration) -> dict[str, str]:
    """The drive's spec parameter and the one member beside it, when it has both."""
    spec = [p.name for p in drive.parameters if p.type.classifier == SPEC]
    snaps = [d.name for d in drives if d is not drive]
    if len(spec) != 1 or len(snaps) != 1:
        return {}
    return {"spec": spec[0], "snap": snaps[0]}


def _count(value: Any) -> bool:
    """A count the holder asks for: ``() -> Int``."""
    arguments = [t for _, t in value.arguments]
    return (
        value.classifier == COUNT
        and len(arguments) == 1
        and arguments[0] is not None
        and arguments[0].classifier == INT
    )


def _factory(
    found: Inventory, classifier: str, index: OptInIndex
) -> Declaration | None:
    """The ``remember...`` composable starting the holder at an ``Int``.

    Of several, the one needing no opt-in: the others extend it with
    experimental parameters.
    """
    factories = [
        d
        for d in found.declarations
        if d.composable
        and d.name.startswith("remember")
        and d.document.get("declarationKind") == "function"
        and _public(d)
        and d.receiver is None
        and d.dispatch_receiver is None
        and d.return_type.classifier == classifier
        and not d.return_type.nullable
        and any(p.type.classifier == INT for p in d.parameters)
        and all(p.has_default or _count(p.type) for p in d.parameters)
    ]
    if len(factories) > 1:
        factories = [d for d in factories if not required_opt_ins(d, index)]
    return factories[0] if len(factories) == 1 else None
