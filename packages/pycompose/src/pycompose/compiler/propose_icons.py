"""Proposal builder for the icon vocabulary."""

from __future__ import annotations

from typing import Any

from pycompose.compiler.classpath_dump import Inventory
from pycompose.compiler.propose_lookup import ancestors, source_name


def propose_icons(
    found: Inventory,
    owner: str,
    family: dict[str, str],
    *,
    since: str,
) -> dict[str, Any]:
    """Propose an icon vocabulary: every public icon under one object.

    ``propose_members`` cannot see these: an icon is an extension property on a
    nested object rather than a member of one class, and the path it is read by
    is the label -- ``Filled.Add``, or ``AutoMirrored.Filled.ArrowBack``. Reading
    it back is a property chain on the same object, so one ``propertyOwner`` plus
    the label spells every native expression and no member needs a holder of its
    own. The packages declaring those extensions are recorded beside it: an
    extension property resolves only when its declaring package is in scope, and
    Kotlin has no syntax for naming one where it stands. A deprecated icon is
    left out rather than offered: ``Icons.Filled.ArrowBack`` was replaced by the
    auto-mirrored one, and a vocabulary that kept the old spelling would
    generate a call that warns at every build.

    Args:
        found: The validated inventory of the current pin.
        owner: Fully qualified object whose nested objects name the icons.
        family: An approved descriptor providing the wire family and Kotlin type.
        since: Schema version that introduced the binding.

    Returns:
        A ``constant`` descriptor keyed by icon label.

    Raises:
        ValueError: The holder has no public icons of that family, so the
            binding would be an empty enumeration presented as support.
    """
    holder = source_name(owner)
    hierarchy = ancestors(found)
    labels: set[str] = set()
    packages: set[str] = set()
    for declaration in found.declarations:
        if declaration.disposition != "support":
            continue
        if declaration.document.get("declarationKind") != "property":
            continue
        receiver = declaration.receiver
        if receiver is None or declaration.context_receivers:
            continue
        where = source_name(receiver.classifier)
        if where == holder:
            label = declaration.name
        elif where.startswith(holder + "."):
            label = f"{where[len(holder) + 1:]}.{declaration.name}"
        else:
            continue
        classifier = source_name(declaration.return_type.classifier)
        if family["kotlinType"] not in hierarchy.get(classifier, {classifier}):
            continue
        if declaration.return_type.nullable or declaration.return_type.arguments:
            raise ValueError(f"{owner}.{declaration.name}: nullable/generic icon")
        if "kotlin/Deprecated" in declaration.annotations:
            continue
        labels.add(label)
        packages.add(declaration.package)
    if not labels:
        raise ValueError(f"no public {family['family']} members on {owner}")
    return {
        "family": family["family"],
        "kind": family.get("kind", "constant"),
        "kotlinType": family["kotlinType"],
        "since": since,
        "source": {"owner": owner, "members": "public properties"},
        "parameters": {
            "name": {
                "type": "string",
                "required": True,
                "values": sorted(labels),
            }
        },
        "native": {
            "constantParameter": "name",
            "propertyOwner": holder,
            "imports": sorted(packages),
        },
    }
