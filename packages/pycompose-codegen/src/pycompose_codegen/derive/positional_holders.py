"""State holders whose family the pin implies: one scrollable position.

``HorizontalPager(state: PagerState)`` scrolls through pages; Python wants to
say which page and hear the page it settles on. That is the whole family
whenever a holder states it in its types:

* it is a ``ScrollableState``, so it is at rest once it stops scrolling;
* its position is the ``Int`` property its constructor also takes
  (``PagerState(currentPage, ...)`` and ``currentPage``);
* its drive is the public suspend member taking just that ``Int``, the one
  that takes an ``AnimationSpec`` where several do, since that one animates;
* its ``remember...`` factory takes an ``Int`` it starts at, and a count
  (``() -> Int``) where it has one, which the host fills with the children.

The host's one positional runtime drives every such holder. A holder the types
leave ambiguous (``LazyListState`` drives by two members alike) is not one.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory
from pycompose_codegen.derive.classpath_types import Declaration

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
        parameters, its position property and its drive.
    """
    members: dict[str, list[Declaration]] = {}
    for declaration in found.declarations:
        owner = declaration.owner.replace(".", "/")
        if _public(declaration):
            members.setdefault(owner, []).append(declaration)
    holders = {}
    for classifier, own in sorted(members.items()):
        supertypes = own[0].document.get("classSupertypes") or []
        if SCROLLABLE not in {t.get("classifier") for t in supertypes}:
            continue
        position = _position(own)
        drive = _drive(own)
        factory = _factory(found, classifier)
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
            "drive": drive,
        }
    return holders


def _public(declaration: Declaration) -> bool:
    return (
        declaration.document.get("visibility") == "PUBLIC"
        and "kotlin/Deprecated" not in declaration.annotations
    )


def _position(own: list[Declaration]) -> str | None:
    """The ``Int`` property the constructor also takes; one, or none."""
    taken = {
        p.name
        for d in own
        if d.document.get("declarationKind") == "constructor"
        for p in d.parameters
        if p.type.classifier == INT
    }
    found = [
        d.name
        for d in own
        if d.document.get("declarationKind") == "property"
        and d.return_type.classifier == INT
        and not d.return_type.nullable
        and d.name in taken
    ]
    return found[0] if len(found) == 1 else None


def _drive(own: list[Declaration]) -> str | None:
    """The suspend member taking just a position, the animating one of several."""
    drives = [
        d
        for d in own
        if d.document.get("declarationKind") == "function"
        and d.document.get("suspend")
        and [p.type.classifier for p in d.parameters if p.required] == [INT]
    ]
    if len(drives) > 1:
        drives = [
            d for d in drives if any(p.type.classifier == SPEC for p in d.parameters)
        ]
    return drives[0].name if len(drives) == 1 else None


def _count(value: Any) -> bool:
    """A count the holder asks for: ``() -> Int``."""
    arguments = [t for _, t in value.arguments]
    return (
        value.classifier == COUNT
        and len(arguments) == 1
        and arguments[0] is not None
        and arguments[0].classifier == INT
    )


def _factory(found: Inventory, classifier: str) -> Declaration | None:
    """The one ``remember...`` composable starting the holder at an ``Int``."""
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
    return factories[0] if len(factories) == 1 else None
