"""Builder scopes whose members are items, and holders a slot is handed.

A container's non-composable builder lambda (``AppBarRowScope.() -> Unit``)
calls its scope's members, one per item (``clickableItem``, ``toggleableItem``).
Each member taking only what a component can carry becomes an item component:
the host applies it in the builder rather than composing it.

A slot lambda may be handed a holder its owner creates (``overflowIndicator:
@Composable (AppBarMenuState) -> Unit``). When the holder's members taking
nothing each set one of its properties to a constant, as the source shows
(``show()`` sets ``isExpanded = true``), the property is projected onto the
slot's owner: the app states it, the host calls the member that sets it, and a
change the holder makes itself is reported.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_types import (
    BUILDERS,
    COMPOSABLE,
    DRAW_SCOPE,
    EXTENSION,
    Declaration,
    Inventory,
)
from pycompose_codegen.derive.propose import SCALARS

Key = tuple[str, str, str]


def member_scopes(found: Inventory) -> dict[str, dict[str, Any]]:
    """Builder receivers whose members are items, by slash classifier.

    The receiver a component's non-composable ``Unit`` extension lambda takes,
    other than a lazy scope or a canvas, whose interfaces declare members.
    """
    classes = {c.classifier.replace(".", "/"): c for c in found.classes}
    declaring = {
        d.dispatch_receiver.classifier
        for d in found.declarations
        if item_member(d) and d.dispatch_receiver is not None
    }
    scopes: dict[str, dict[str, Any]] = {}
    for declaration in found.ui:
        for parameter in declaration.parameters:
            value = parameter.type
            receiver = value.arguments[0][1] if value.arguments else None
            if (
                receiver is None
                or COMPOSABLE in value.annotations
                or EXTENSION not in value.annotations
                or receiver.classifier in BUILDERS | {DRAW_SCOPE}
                or receiver.nullable
                or receiver.arguments
            ):
                continue
            items = sorted(_lineage(receiver.classifier, classes) & declaring)
            if items:
                scopes[receiver.classifier] = {"kind": "members", "items": items}
    return scopes


def item_member(declaration: Declaration) -> bool:
    """Whether a public declaration is a scope member a builder calls for an item."""
    returns = declaration.return_type
    return (
        declaration.disposition == "support"
        and not declaration.composable
        and declaration.dispatch_receiver is not None
        and declaration.receiver is None
        and returns is not None
        and returns.classifier == "kotlin/Unit"
        and declaration.document.get("declarationKind") == "function"
    )


def item_name(declaration: Declaration, taken: frozenset[str]) -> str:
    """An item component's name: its scope's, less ``Scope``, then the member's.

    ``AppBarScope.clickableItem`` is ``AppBarClickableItem``. Where that names a
    composable already (``NavigationSuiteScope.item``), the scope keeps its
    whole name: ``NavigationSuiteScopeItem``.
    """
    scope = (declaration.dispatch_receiver or declaration.return_type).classifier
    simple = scope.rsplit("/", 1)[-1].rsplit("$", 1)[-1]
    member = declaration.name[:1].upper() + declaration.name[1:]
    short = simple.removesuffix("Scope") + member
    return short if short not in taken else simple + member


def item_sources(found: Inventory) -> list[Declaration]:
    """The members every item scope declares: candidates beside the components."""
    scopes = {s for spec in member_scopes(found).values() for s in spec["items"]}
    return [
        d
        for d in found.declarations
        if item_member(d)
        and d.dispatch_receiver is not None
        and d.dispatch_receiver.classifier in scopes
    ]


def handed_holders(
    found: Inventory, drives: dict[Key, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Holders whose bare members set one scalar property, by slash classifier.

    Every public member taking nothing must carry assignment evidence for the
    same property, and together they must set each value it takes once: a
    ``Boolean`` set ``true`` by one member and ``false`` by another.
    """
    members = {
        (d.owner, d.jvm_name or "", d.jvm_descriptor or ""): d
        for d in found.declarations
    }
    by_holder: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for key, drive in drives.items():
        if drive.get("kind") == "assigns" and key in members:
            by_holder.setdefault(key[0], []).append((members[key].name, drive))
    holders: dict[str, dict[str, Any]] = {}
    for holder, assigned in by_holder.items():
        bare = {
            d.name
            for d in found.declarations
            if d.owner == holder and item_member_shape(d)
        }
        properties = {drive["property"] for _, drive in assigned}
        values = [drive["value"] for _, drive in assigned]
        read = _property(found, holder, next(iter(properties)))
        if (
            len(properties) != 1
            or bare != {name for name, _ in assigned}
            or read is None
            or SCALARS.get(read) != "boolean"
            or sorted(values) != [False, True]
        ):
            continue
        holders[holder.replace(".", "/")] = {
            "kind": "handed",
            "holder": holder,
            "value": next(iter(properties)),
            "drives": {
                "true" if drive["value"] else "false": name for name, drive in assigned
            },
        }
    return holders


def item_member_shape(declaration: Declaration) -> bool:
    """A public member function taking nothing: what a holder's drive looks like."""
    return (
        declaration.disposition in {"ui", "support"}
        and declaration.dispatch_receiver is not None
        and not declaration.parameters
        and declaration.document.get("declarationKind") == "function"
    )


def _property(found: Inventory, holder: str, name: str) -> str | None:
    """The slash classifier of a holder's public property, or None."""
    for d in found.declarations:
        if (
            d.owner == holder
            and d.name == name
            and d.disposition in {"ui", "support"}
            and d.document.get("declarationKind") == "property"
            and d.return_type is not None
            and not d.return_type.nullable
        ):
            return d.return_type.classifier
    return None


def _lineage(classifier: str, classes: dict[str, Any]) -> set[str]:
    """A class and every supertype the pin records for it, by slash classifier."""
    seen: set[str] = set()
    pending = [classifier]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        known = classes.get(current)
        if known is not None:
            pending.extend(known.supertypes)
    return seen


def drop_itemless(components: dict[str, Any]) -> dict[str, str]:
    """Remove each component whose builder no item component can fill.

    A builder's scope is useful on the wire only when some item component
    applies to it; one whose every member was refused
    (``AndroidExternalSurfaceScope.onSurface``) builds nothing.

    Args:
        components: The compiled components, pruned in place.

    Returns:
        The reason, per component removed.
    """
    filled = {e["scope"] for e in components.values() if e.get("item")}
    dropped = {}
    for name, entry in list(components.items()):
        channels = [entry.get("children", {}), *entry.get("slots", {}).values()]
        for channel in channels:
            applied = filled & set(channel.get("applies", ()))
            if channel.get("kind") == "members" and not applied:
                dropped[name] = f"no item component fills {channel['provides']}"
                del components[name]
                break
    return dropped
