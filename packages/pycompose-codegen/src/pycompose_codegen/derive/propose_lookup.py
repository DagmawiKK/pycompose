"""Shared lookup helpers and selector policies for schema proposals.

The proposal workflow reads pinned classpath dumps and the approved registry.
This layer owns the pure lookups: alias tables (:data:`SCALARS`,
:data:`ROLES`, :data:`OBJECT_KINDS`, :data:`POLICIES`, :data:`MEMBERS`,
:data:`EXTENSIONS`, :data:`ICONS`), source-name normalization
(:func:`source_name`), the ancestry check (:func:`ancestors`), whether a type
is :func:`assignable`, the rule renderer (:func:`_rule`), proposal
``identity`` and the rebind selectors (:func:`select`, :func:`preferred`,
:func:`_matches_rule`, :func:`_preserve_constraints`).

Proposers live in ``propose_families`` and ``propose_icons``; the CLI and the
refresh loop live in ``propose``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pycompose_codegen.derive.classpath_dump import (
    Declaration,
    Inventory,
    KotlinType,
)

SCALARS = {
    "kotlin/Int": "int",
    "kotlin/Long": "long",
    "kotlin/Float": "float",
    "kotlin/Double": "double",
    "kotlin/String": "string",
    "kotlin/Boolean": "boolean",
}
ROLES = {"scalar", "record", "factory", "constant", "reference"}
OBJECT_KINDS = {"OBJECT", "COMPANION_OBJECT"}
"""A companion object is as callable as an object; both are static holders."""
POLICIES = {
    "androidx/compose/ui/geometry/Size": {"minimum": 0},
    "androidx/compose/foundation/layout/PaddingValues": {"minimum": 0},
    "androidx/compose/foundation/layout/WindowInsets": {"minimum": 0},
}
"""Small reusable per-family rules. Anything else is reported, never guessed.

``Dp`` deliberately carries no bounds here: offsets and sizes are signed in
Compose, so a blanket floor would refuse legal values. Non-negative floors that
really are semantics stay as approved, preserved facts on the entries that
declare them.
"""


def source_name(classifier: str) -> str:
    """Spell a metadata classifier the way Kotlin source spells it.

    Compose metadata separates packages with ``/`` and nested classes with
    ``.``, while approved ``kotlinType`` values are source references. Every
    comparison normalises the classifier, never the approved name, so a nested
    class and a package boundary stay distinguishable.
    """
    return classifier.replace("/", ".")


def ancestors(found: Inventory) -> dict[str, set[str]]:
    """Map every pinned class to itself plus its declared supertypes.

    Only recorded class facts count, and every class counts: a class that
    declares nothing still says what it extends. ``Alignment.Vertical`` is a
    sibling of ``Alignment`` rather than a subtype, so a member vocabulary can
    tell an assignable type from a neighbouring one instead of guessing from a
    name or silently narrowing to the members it happens to see.
    """
    families: dict[str, set[str]] = {}

    def record(classifier: str, parents: Iterable[str]) -> None:
        found_types = families.setdefault(classifier, {classifier})
        found_types.update(parents)
        for parent in parents:
            families.setdefault(parent, {parent})

    for evidence in found.classes:
        record(
            source_name(evidence.classifier),
            [source_name(parent) for parent in evidence.supertypes],
        )
    for declaration in found.declarations:
        record(source_name(declaration.return_type.classifier), ())
    # Supertypes are only declared one level deep, so close the relation: a
    # grandchild is as assignable as its parent.
    for classifier in list(families):
        pending, reached = list(families[classifier]), set(families[classifier])
        while pending:
            parent = pending.pop()
            for grandparent in families.get(parent, {parent}):
                if grandparent not in reached:
                    reached.add(grandparent)
                    pending.append(grandparent)
        families[classifier] = reached
    return families


def assignable(found: Inventory, family: dict[str, str], source: str) -> bool:
    """Report whether ``source`` is the family's type or one of its subtypes."""
    if source_name(source) == family["kotlinType"]:
        return True
    return family["kotlinType"] in ancestors(found).get(source_name(source), set())


def value_families(registry: dict[str, Any]) -> dict[str, str]:
    """Map every implemented native type to its wire family.

    Args:
        registry: The approved component registry.

    Returns:
        Source-spelled native type names keyed to family names. Compare a dump
        classifier through ``source_name`` first.
    """
    return {
        spec["kotlinType"]: spec["family"]
        for spec in registry.get("valueTypes", {}).values()
        if "family" in spec
    }


def _rule(value: KotlinType, families: dict[str, str]) -> dict[str, Any]:
    if value.classifier in SCALARS:
        result: dict[str, Any] = {"type": SCALARS[value.classifier]}
    elif source_name(value.classifier) in families:
        result = {"type": "value", "valueType": families[source_name(value.classifier)]}
    elif value.classifier == "kotlin/collections/List" and len(value.arguments) == 1:
        item = value.arguments[0][1]
        if item is None:
            raise ValueError("star-projected list has no wire policy")
        result = {"type": "list", "items": _rule(item, families)}
    else:
        raise ValueError(f"no value policy for {value.classifier}")
    if value.nullable:
        result["nullable"] = True
    result.update(POLICIES.get(value.classifier, {}))
    return result


def identity(source: Declaration, *, pinned: bool = True) -> dict[str, Any]:
    """Return exact artifact/JVM identity for approval and subsequent drift checks.

    Args:
        source: The pinned declaration being bound.
        pinned: Include the artifact coordinate, so a release bump is visible.

    Returns:
        The schema's ``source`` block for this declaration.
    """
    return {
        **({"artifact": source.artifact} if pinned else {}),
        "owner": source.owner,
        "name": source.name,
        "jvmName": source.jvm_name,
        "descriptor": source.jvm_descriptor,
    }


def _role(constructor: bool, parameters: dict[str, Any], approved: str | None) -> str:
    """Classify by native shape, preserving an approved non-value role."""
    if approved is not None:
        if approved not in ROLES:
            raise ValueError(f"unsupported value role: {approved}")
        return approved
    return "scalar" if len(parameters) == 1 else "record" if constructor else "factory"


def select(
    found: Inventory, approved: dict[str, Any] | None, name: str
) -> list[Declaration]:
    """Return the pinned overloads a binding may refer to.

    Exact JVM identity is authoritative, so overloads never collapse. When the
    approved descriptor has moved -- a release may change any parameter type --
    fall back to same-named candidates *on the same owner*, and let the reader
    choose. Anything wider is a refusal, not a guess: a rename must surface as a
    decision rather than silently rebinding a different symbol.

    Args:
        found: The validated inventory of the current pin.
        approved: The approved ``source`` block, or None to look a name up.
        name: The schema constructor name.

    Returns:
        Candidate declarations, or none when nothing plausible remains.
    """
    callables = [d for d in found.declarations if d.disposition == "support"]
    if approved is None:
        return [
            d
            for d in callables
            if d.name == name
            or (d.name == "<init>" and d.owner.rsplit(".", 1)[-1] == name)
        ]
    wanted = {key: value for key, value in approved.items() if key != "artifact"}
    exact = [
        d
        for d in callables
        if all(
            identity(d, pinned=False).get(key) == value for key, value in wanted.items()
        )
    ]
    if exact:
        return exact
    return [
        d
        for d in callables
        if identity(d, pinned=False)["owner"] == approved["owner"]
        and d.name == approved["name"]
    ]


def preferred(
    matches: list[Declaration],
    approved: dict[str, Any],
    families: dict[str, str],
) -> list[Declaration]:
    """Narrow overloads to the one an approved binding already exposes.

    A refresh must not silently reshape an app's public API, so the approved
    parameter names *and* types decide. Two overloads that agree on neither are
    returned untouched, which surfaces them as a decision instead of a coin flip.

    Args:
        matches: Candidate declarations for one binding.
        approved: The approved parameter rules, by name.
        families: Native classifier to wire family, for already-bound families.

    Returns:
        Complete name/type matches, or all candidates when none match.
    """
    if len(matches) < 2 or not approved:
        return matches
    winners = [
        declaration
        for declaration in matches
        if all(
            any(
                p.name == name and _matches_rule(rule, p.type, families)
                for p in declaration.parameters
            )
            for name, rule in approved.items()
        )
    ]
    return winners or matches


def _matches_rule(
    rule: dict[str, Any], value: KotlinType, families: dict[str, str]
) -> bool:
    """Report whether an approved rule already describes a source parameter."""
    if rule.get("type") == "value":
        return families.get(source_name(value.classifier)) == rule.get("valueType")
    if rule.get("type") == "list":
        return (
            value.classifier == "kotlin/collections/List"
            and len(value.arguments) == 1
            and value.arguments[0][1] is not None
            and _matches_rule(rule["items"], value.arguments[0][1], families)
        )
    return rule.get("type") == SCALARS.get(value.classifier)


def _preserve_constraints(rule: dict[str, Any], approved: dict[str, Any]) -> None:
    """Keep approved wire validation policy; never copy native/default facts."""
    rule.update(
        {
            key: approved[key]
            for key in ("minimum", "maximum", "minItems")
            if key in approved
        }
    )
    if rule["type"] == "list" and approved.get("type") == "list":
        _preserve_constraints(rule["items"], approved["items"])


MEMBERS = {
    "ThemeColor": (
        "androidx/compose/material3/ColorScheme",
        "androidx.compose.material3.MaterialTheme.colorScheme.",
        (),
    ),
    "ThemeTypography": (
        "androidx/compose/material3/Typography",
        "androidx.compose.material3.MaterialTheme.typography.",
        (),
    ),
    "ThemeShape": (
        "androidx/compose/material3/Shapes",
        "androidx.compose.material3.MaterialTheme.shapes.",
        (),
    ),
    "FontFamily": ("androidx/compose/ui/text/font/FontFamily$Companion", "", ()),
    "ToggleableState": ("androidx/compose/ui/state/ToggleableState", "", ()),
    "StrokeCap": ("androidx/compose/ui/graphics/StrokeCap$Companion", "", ()),
    "TextAlign": ("androidx/compose/ui/text/style/TextAlign$Companion", "", ()),
    "TextDecoration": (
        "androidx/compose/ui/text/style/TextDecoration$Companion",
        "",
        (),
    ),
    "TextOverflow": (
        "androidx/compose/ui/text/style/TextOverflow$Companion",
        "",
        (),
    ),
    "FontStyle": ("androidx/compose/ui/text/font/FontStyle$Companion", "", ()),
    "FabPosition": ("androidx/compose/material3/FabPosition$Companion", "", ()),
    "TimePickerLayoutType": (
        "androidx/compose/material3/TimePickerLayoutType$Companion",
        "",
        (),
    ),
    "DisplayMode": ("androidx/compose/material3/DisplayMode$Companion", "", ()),
    # AbsoluteAlignment is a second holder of the alignment vocabulary, not a
    # whole new one: its members carry the same family types, so they join the
    # family under their own holder.
    "Alignment": (
        "androidx/compose/ui/Alignment$Companion",
        "",
        ("androidx/compose/ui/AbsoluteAlignment",),
    ),
    "AlignmentVertical": (
        "androidx/compose/ui/Alignment$Companion",
        "",
        (),
    ),
    "AlignmentHorizontal": (
        "androidx/compose/ui/Alignment$Companion",
        "",
        ("androidx/compose/ui/AbsoluteAlignment",),
    ),
}
"""Bindings whose wire vocabulary is the public member set of one class.

This table names *which* class a family reads; it never lists a member. The
names, their Kotlin spelling and their count all come from the pinned artifact.
"""
EXTENSIONS = {"Sp": "sp", "Em": "em"}
"""Bindings that mirror a public extension property over a scalar."""
ICONS = {"materialIcon": "androidx/compose/material/icons/Icons"}
"""Bindings whose wire vocabulary is every icon under one object.

The holder is named, never its members: ``Icons`` carries the styles and their
auto-mirrored twins, and each icon is a property on one of those, so the pinned
artifact decides the whole vocabulary and its count.
"""
