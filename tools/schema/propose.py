"""Propose value bindings from the pinned inventory; never edit the approved schema.

Run ``./gradlew dumpComposeDefaults`` in android/ first, then e.g.
``python tools/schema/propose.py Dp --out proposal.json``, or
``python tools/schema/propose.py --refresh`` to rebind the whole catalog.

Three shapes of public API are covered, each by one reusable policy:

* an ordinary constructor or factory (``propose_value``)
* the named members of a class -- every public property of a given type
  (``propose_members``), which is how theme roles and families are derived
* an extension property over a scalar (``propose_extension``)

Anything else is refused with a reason, never guessed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema.classpath_dump import (
    DUMP_DIR,
    Declaration,
    Inventory,
    KotlinType,
    inventory,
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
    "androidx/compose/ui/unit/Dp": {"minimum": 0},
    "androidx/compose/ui/geometry/Size": {"minimum": 0},
    "androidx/compose/foundation/layout/PaddingValues": {"minimum": 0},
    "androidx/compose/foundation/layout/WindowInsets": {"minimum": 0},
}
"""Small reusable per-family rules. Anything else is reported, never guessed."""


def ancestors(found: Inventory) -> dict[str, set[str]]:
    """Map every classified class to itself plus its declared supertypes.

    Only ``classSupertypes`` counts. A type mentioned in a signature is not a
    supertype, and treating it as one would make every family accept every type.
    """
    families: dict[str, set[str]] = {}

    def record(classifier: str, parents: Iterable[str]) -> None:
        found_types = families.setdefault(classifier, {classifier})
        found_types.update(parents)
        for parent in parents:
            families.setdefault(parent, {parent})

    for declaration in found.declarations:
        slashed = declaration.owner.replace(".", "/")
        for node in declaration.document.get("classSupertypes") or []:
            parent = node.get("classifier")
            if parent:
                record(slashed, [parent])
    for declaration in found.declarations:
        record(declaration.return_type.classifier, ())
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
    if source == family["kotlinType"].replace(".", "/"):
        return True
    return family["kotlinType"].replace(".", "/") in ancestors(found).get(source, set())


def value_families(registry: dict[str, Any]) -> dict[str, str]:
    """Map every implemented native type to its wire family.

    Args:
        registry: The approved component registry.

    Returns:
        Native type names, ``/``-separated, keyed to family names.
    """
    return {
        spec["kotlinType"].replace(".", "/"): spec["family"]
        for spec in registry.get("valueTypes", {}).values()
        if "family" in spec
    }


def _rule(value: KotlinType, families: dict[str, str]) -> dict[str, Any]:
    if value.classifier in SCALARS:
        result: dict[str, Any] = {"type": SCALARS[value.classifier]}
    elif value.classifier in families:
        result = {"type": "value", "valueType": families[value.classifier]}
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


def propose_value(
    source: Declaration,
    *,
    since: str,
    families: dict[str, str],
    defaults: dict[str, Any] | None = None,
    role: str | None = None,
    approved_family: str | None = None,
    surface: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Derive an ordinary constructor/factory using reusable type/default policies.

    Args:
        source: The exact pinned declaration to bind.
        since: Schema version that introduced the binding.
        families: Native classifier to wire family, for already-bound families.
        defaults: Compiler-resolved defaults keyed by JVM identity, when known.
        role: An approved wire role to preserve instead of re-deriving.
        approved_family: An approved family to preserve, so values stay
            interchangeable where the wire treats them alike.
        surface: Approved parameter names. Other optional arguments remain native.

    Returns:
        A value descriptor that is a drop-in candidate for ``valueTypes``.

    Raises:
        ValueError: The declaration needs a policy a proposal must not invent.
    """
    _validate_callable(source)
    native_type = source.return_type.classifier.replace("/", ".")
    if native_type.startswith("kotlin."):
        raise ValueError("not a native value family")
    family = families.get(source.return_type.classifier, native_type.rsplit(".", 1)[-1])
    parameters = {}
    omitted = {}
    for parameter in source.parameters:
        if surface is not None and parameter.name not in surface:
            if parameter.required:
                raise ValueError(
                    f"{parameter.name}: required argument outside approved surface"
                )
            omitted[parameter.name] = {
                "type": parameter.type.classifier,
                "nullable": parameter.type.nullable,
                "hasDefault": parameter.has_default,
            }
            continue
        if parameter.vararg_type:
            raise ValueError(f"{parameter.name}: varargs need a collection policy")
        rule = _rule(parameter.type, families)
        if parameter.has_default:
            if defaults is None or parameter.name not in defaults:
                raise ValueError(f"{parameter.name}: missing compiler-resolved default")
            expression = defaults[parameter.name]
            if expression.get("kind") == "unsupported":
                raise ValueError(f"{parameter.name}: {expression['reason']}")
            rule["default"] = expression
        else:
            rule["required"] = True
        parameters[parameter.name] = rule
    if surface is not None:
        if set(surface) != set(parameters):
            raise ValueError("approved parameter is missing from the native signature")
        parameters = {field: parameters[field] for field in surface}
    constructor = source.document["declarationKind"] == "constructor"
    owner = (
        source.owner.replace("$", ".") if source.dispatch_receiver else source.package
    )
    call = native_type if constructor else owner + "." + source.name
    result = {
        "family": approved_family or family,
        "kind": _role(constructor, parameters, role),
        "kotlinType": native_type,
        "since": since,
        "source": identity(source),
        "parameters": parameters,
        "native": {"call": call},
    }
    if omitted:
        result["omitted"] = omitted
    return result


def _validate_callable(source: Declaration) -> None:
    if source.disposition != "support" or source.receiver or source.context_receivers:
        raise ValueError("not a public, receiver-free value callable")
    if source.document.get("declarationKind") not in {"function", "constructor"}:
        raise ValueError("not a constructor or factory")
    if (
        source.dispatch_receiver
        and source.document.get("classKind") not in OBJECT_KINDS
    ):
        raise ValueError("instance methods need an explicit native receiver protocol")
    if source.return_type.nullable or source.return_type.arguments:
        raise ValueError("nullable/generic return needs an explicit value policy")


def propose_members(
    found: Inventory,
    owner: str,
    family: dict[str, str],
    *,
    since: str,
    prefix: str = "",
) -> dict[str, Any]:
    """Propose a named-member binding: every public member of ``owner`` in ``family``.

    This is the single policy behind theme roles, typography and shapes. The
    names are facts about the pinned class, so a release that adds or renames a
    role shows up as a proposal diff rather than a rendering difference.

    Args:
        found: The validated inventory of the current pin.
        owner: Fully qualified class whose public members become wire names.
        family: An approved descriptor providing the wire family and Kotlin type.
        since: Schema version that introduced the binding.
        prefix: Optional native qualifier, e.g. a ``MaterialTheme`` holder.

    Returns:
        A ``constant`` descriptor keyed by member name.

    Raises:
        ValueError: The owner has no members of that family, so the binding would
            be an empty enumeration presented as support.
    """
    members = set()
    hierarchy = ancestors(found)
    dotted = owner.replace("/", ".")
    for declaration in found.declarations:
        if declaration.owner != dotted or declaration.disposition != "support":
            continue
        if declaration.document.get("declarationKind") != "property":
            continue
        if family["kotlinType"].replace(".", "/") not in hierarchy.get(
            declaration.return_type.classifier, {declaration.return_type.classifier}
        ):
            continue
        if declaration.return_type.nullable or declaration.return_type.arguments:
            raise ValueError(f"{owner}.{declaration.name}: nullable/generic member")
        if declaration.context_receivers or declaration.receiver:
            continue
        members.add(declaration.name)
    if not members:
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
                "values": sorted(members),
            }
        },
        "native": {
            "constantParameter": "name",
            "propertyOwner": prefix.rstrip(".") or dotted.replace("$Companion", ""),
        },
    }


def propose_extension(
    found: Inventory,
    name: str,
    receiver: str,
    family: dict[str, str],
    *,
    since: str,
) -> dict[str, Any]:
    """Propose an extension property binding such as ``Float.sp`` -> ``TextUnit``.

    The wire constructor mirrors the extension: the value carries the receiver's
    type and the native side applies the extension. A receiver the wire does not
    have a scalar for is refused rather than coerced.

    Args:
        found: The validated inventory of the current pin.
        name: The extension property name, as Compose declares it.
        receiver: The classifier the extension is declared on.
        family: An approved descriptor providing the wire family and Kotlin type.
        since: Schema version that introduced the binding.

    Returns:
        A ``scalar`` descriptor that renders the extension natively.

    Raises:
        ValueError: No such public extension, or its receiver is not a scalar.
    """
    if receiver != "kotlin/Float":
        raise ValueError(f"no native extension receiver policy for {receiver}")
    matches = [
        d
        for d in found.declarations
        if d.disposition == "support"
        and d.document.get("declarationKind") == "property"
        and d.name == name
        and d.receiver is not None
        and d.receiver.classifier == receiver
        and d.return_type.classifier == family["kotlinType"].replace(".", "/")
        and not d.return_type.nullable
        and not d.return_type.arguments
        and not d.context_receivers
        and not d.dispatch_receiver
        and not d.parameters
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {receiver}.{name} extension, found {len(matches)}"
        )
    return {
        "family": family["family"],
        "kind": "scalar",
        "kotlinType": family["kotlinType"],
        "since": since,
        "source": identity(matches[0]),
        "parameters": {"value": {"type": SCALARS[receiver], "required": True}},
        "native": {"extension": name},
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
        return families.get(value.classifier) == rule.get("valueType")
    if rule.get("type") == "list":
        return (
            value.classifier == "kotlin/collections/List"
            and len(value.arguments) == 1
            and value.arguments[0][1] is not None
            and _matches_rule(rule["items"], value.arguments[0][1], families)
        )
    return rule.get("type") == SCALARS.get(value.classifier)


def bind(
    found: Inventory,
    evidence: dict[tuple[str, str, str], dict[str, Any]],
    registry: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    """Propose one approved binding against the current pin, or explain the refusal."""
    approved = registry["valueTypes"].get(name, {})
    since = approved.get("since", registry["schemaVersion"])
    try:
        if name in MEMBERS:
            owner, prefix = MEMBERS[name]
            return {
                "name": name,
                "proposal": propose_members(
                    found, owner, approved, since=since, prefix=prefix
                ),
            }
        if name in EXTENSIONS:
            return {
                "name": name,
                "proposal": propose_extension(
                    found, EXTENSIONS[name], "kotlin/Float", approved, since=since
                ),
            }
    except ValueError as exc:
        return {"name": name, "unsupported": str(exc)}
    families = value_families(registry)
    matches = select(found, approved.get("source"), name)
    if not matches:
        return {"name": name, "unsupported": "no public value callable at this pin"}
    matches = preferred(matches, approved.get("parameters", {}), families)
    proposals = []
    for source in matches:
        item: dict[str, Any] = {"name": name, "source": identity(source)}
        try:
            item["proposal"] = propose_value(
                source,
                since=since,
                families=families,
                defaults=evidence.get(
                    (source.owner, source.jvm_name, source.jvm_descriptor)
                ),
                role=approved.get("kind"),
                approved_family=approved.get("family"),
                surface=tuple(approved["parameters"])
                if "parameters" in approved
                else None,
            )
            if "kotlinType" in approved:
                if not assignable(found, approved, source.return_type.classifier):
                    raise ValueError(
                        "native result is not assignable to the approved family"
                    )
                item["proposal"]["kotlinType"] = approved["kotlinType"]
            for field, rule in item["proposal"]["parameters"].items():
                _preserve_constraints(
                    rule, approved.get("parameters", {}).get(field, {})
                )
        except ValueError as exc:
            item.pop("proposal", None)
            item["unsupported"] = str(exc)
        proposals.append(item)
    if len(proposals) > 1:
        return {
            "name": name,
            "candidates": proposals,
            "reason": "choose the overload to bind",
        }
    result = proposals[0]
    if "source" in approved and identity(matches[0]) != approved["source"]:
        result["replaces"] = approved["source"]
    return result


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
    ),
    "ThemeTypography": (
        "androidx/compose/material3/Typography",
        "androidx.compose.material3.MaterialTheme.typography.",
    ),
    "ThemeShape": (
        "androidx/compose/material3/Shapes",
        "androidx.compose.material3.MaterialTheme.shapes.",
    ),
    "FontFamily": ("androidx/compose/ui/text/font/FontFamily$Companion", ""),
}
"""Bindings whose wire vocabulary is the public member set of one class.

This table names *which* class a family reads; it never lists a member. The
names, their Kotlin spelling and their count all come from the pinned artifact.
"""
EXTENSIONS = {"Sp": "sp", "Em": "em"}
"""Bindings that mirror a public extension property over a scalar."""


def refresh(
    found: Inventory,
    evidence: dict[tuple[str, str, str], dict[str, Any]],
    registry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Re-derive every approved binding without changing the approved schema.

    Args:
        found: The validated inventory of the current pin.
        evidence: Compiler-resolved defaults keyed by JVM identity.
        registry: The approved catalog.

    Returns:
        One result per binding: a proposal, explicit candidates, or a refusal.
    """
    return [
        bind(found, evidence, registry, name)
        for name, spec in registry["valueTypes"].items()
        if "family" in spec
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rebind every approved value binding against the current pin.",
    )
    parser.add_argument("--directory", type=Path, default=DUMP_DIR)
    parser.add_argument("--schema", type=Path, default=Path("schema/components.json"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        from schema.classpath_dump import source_defaults

        found = inventory(args.directory)
        evidence = source_defaults(args.directory)
        registry = json.loads(args.schema.read_text())
        if args.refresh or not args.names:
            if args.names:
                raise ValueError("--refresh rebinds the whole catalog; drop the names")
            proposals = refresh(found, evidence, registry)
        else:
            proposals = [bind(found, evidence, registry, name) for name in args.names]
        text = json.dumps(proposals, indent=2) + "\n"
        if args.out:
            if args.out.resolve() == args.schema.resolve():
                raise ValueError("proposals cannot overwrite the approved schema")
            args.out.write_text(text)
        else:
            print(text, end="")
    except (OSError, ValueError) as exc:
        print(f"propose.py: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
