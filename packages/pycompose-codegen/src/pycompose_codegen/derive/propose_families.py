"""The proposal builders for schema approval: one policy per Compose shape.

* an ordinary constructor or factory (:func:`propose_value`), with its
  rebinding contract (:func:`bind`)
* the named members of a class (:func:`propose_members`)
* an extension property over a scalar (:func:`propose_extension`)
* the extended member vocabulary (:func:`propose_vocabulary`)

Anything else is refused with a reason, never guessed. Shared lookups and
selectors live one layer down in ``propose_lookup``; icons live in
``propose_icons``; the CLI and refresh loop live in ``propose``.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Declaration, Inventory
from pycompose_codegen.derive.opt_ins import OptInIndex, opt_in_index, required_opt_ins
from pycompose_codegen.derive.propose_icons import propose_icons
from pycompose_codegen.derive.propose_lookup import (
    EXTENSIONS,
    ICONS,
    MEMBERS,
    OBJECT_KINDS,
    SCALARS,
    _preserve_constraints,
    _role,
    _rule,
    ancestors,
    assignable,
    identity,
    preferred,
    select,
    source_name,
    value_families,
)

#: The opt-in index a caller gets when no pin evidence is passed in.
EMPTY_OPT_INS = OptInIndex()


def _refuse_inaccessible(required: set[str], opt_ins: OptInIndex) -> None:
    """Fail closed when a required marker cannot be named outside the pin.

    Args:
        required: The markers the binding would have to opt in to.
        opt_ins: The pin's opt-in index.

    Raises:
        ValueError: A required marker is declared non-public upstream, so no
            generated call site could ever name it.
    """
    inaccessible = sorted(required & opt_ins.inaccessible)
    if inaccessible:
        raise ValueError(
            "opt-in marker is not accessible outside the pin: "
            + ", ".join(inaccessible)
        )


def propose_value(
    source: Declaration,
    *,
    since: str,
    families: dict[str, str],
    defaults: dict[str, Any] | None = None,
    role: str | None = None,
    approved_family: str | None = None,
    surface: tuple[str, ...] | None = None,
    opt_ins: OptInIndex = EMPTY_OPT_INS,
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
        opt_ins: The pin's opt-in index; the entry carries the markers this
            declaration requires, so a generated call site can opt in exactly.

    Returns:
        A value descriptor that is a drop-in candidate for ``valueTypes``.

    Raises:
        ValueError: The declaration needs a policy a proposal must not invent.
    """
    _validate_callable(source)
    native_type = source.return_type.classifier.replace("/", ".")
    if native_type.startswith("kotlin."):
        raise ValueError("not a native value family")
    family = families.get(native_type, native_type.rsplit(".", 1)[-1])
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
    required = required_opt_ins(source, opt_ins)
    _refuse_inaccessible(required, opt_ins)
    result = {
        "family": approved_family or family,
        "kind": _role(constructor, parameters, role),
        "kotlinType": native_type,
        "since": since,
        "source": identity(source),
        **({"optIn": sorted(required)} if required else {}),
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
    if source.document.get(
        "declarationKind"
    ) == "constructor" and source.class_modality in {"ABSTRACT", "SEALED"}:
        # `Painter()` is a bytecode constructor no app can ever call, so a
        # family built from it would compile nothing and mean nothing.
        raise ValueError("class cannot be constructed")
    if (
        source.dispatch_receiver
        and source.document.get("classKind") not in OBJECT_KINDS
    ):
        raise ValueError("instance methods need an explicit native receiver protocol")
    if source.return_type.nullable or source.return_type.arguments:
        raise ValueError("nullable/generic return needs an explicit value policy")


def _holder(declaration: Declaration, classes: set[str]) -> str:
    """How Kotlin source names what holds a member.

    A companion is named by its class. A top-level value lives in a file facade
    (``RectangleShapeKt``) the pin declares no class for and Kotlin cannot
    name; its member is named by its package instead.
    """
    if declaration.owner not in classes and declaration.owner.endswith("Kt"):
        return declaration.package
    return declaration.owner.replace("$Companion", "").replace("$", ".")


def propose_members(
    found: Inventory,
    owner: str,
    family: dict[str, str],
    *,
    since: str,
    prefix: str = "",
    opt_ins: OptInIndex = EMPTY_OPT_INS,
    also_from: tuple[str, ...] = (),
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
        opt_ins: The pin's opt-in index; a member that needs a marker contributes
            it, and an inaccessible marker fails the proposal closed.
        also_from: Further approved holders of the same vocabulary, such as an
            object whose members carry the family's type. A member keeps the
            holder it is read from, so nothing is renamed to fit one prefix.

    Returns:
        A ``constant`` descriptor keyed by member name.

    Raises:
        ValueError: The holders have no members of that family, so the binding
            would be an empty enumeration presented as support.
    """
    primary = source_name(owner)
    holders = {primary, *(source_name(name) for name in also_from)}
    members: dict[str, str] = {}
    required: set[str] = set()
    entries: set[str] = set()
    hierarchy = ancestors(found)
    classes = {c.classifier for c in found.classes}
    for declaration in found.declarations:
        if declaration.owner not in holders:
            continue
        if declaration.owner == primary:
            entries.update(declaration.enum_entries)
        if declaration.disposition != "support":
            continue
        if declaration.document.get("declarationKind") != "property":
            continue
        classifier = source_name(declaration.return_type.classifier)
        if family["kotlinType"] not in hierarchy.get(classifier, {classifier}):
            continue
        if declaration.return_type.nullable or declaration.return_type.arguments:
            raise ValueError(f"{owner}.{declaration.name}: nullable/generic member")
        if declaration.context_receivers or declaration.receiver:
            continue
        members[declaration.name] = prefix.rstrip(".") or _holder(declaration, classes)
        required |= required_opt_ins(declaration, opt_ins)
    if not members and not entries:
        raise ValueError(f"no public {family['family']} members on {owner}")
    _refuse_inaccessible(required, opt_ins)
    described = (
        "enum entries"
        if entries and not members
        else "public properties"
        if members and not entries
        else "enum entries and public properties"
    )
    holder = prefix.rstrip(".") or next(
        (_holder(d, classes) for d in found.declarations if d.owner == primary),
        primary.replace("$Companion", "").replace("$", "."),
    )
    native: dict[str, Any] = {
        "constantParameter": "name",
        "propertyOwner": holder,
    }
    # A vocabulary can live on more than one holder. Only the members that
    # differ from the default carry their holder, so the schema states the
    # exception instead of repeating the rule.
    others = {name: where for name, where in sorted(members.items()) if where != holder}
    if others:
        native["owners"] = others
    return {
        "family": family["family"],
        "kind": family.get("kind", "constant"),
        "kotlinType": family["kotlinType"],
        "since": since,
        "source": {"owner": owner, "members": described},
        **({"optIn": sorted(required)} if required else {}),
        "parameters": {
            "name": {
                "type": "string",
                "required": True,
                "values": sorted(set(members) | entries),
            }
        },
        "native": native,
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
        and source_name(d.return_type.classifier) == family["kotlinType"]
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


def propose_vocabulary(
    found: Inventory,
    approved: dict[str, Any],
    name: str,
    *,
    since: str,
    index: OptInIndex,
) -> dict[str, Any] | None:
    """Propose a member, unit or icon vocabulary, or nothing the tables know.

    The three differ in what the pin has to show. A member vocabulary is read off
    one holder's own members, the unit extensions mirror a scalar Kotlin spells
    as a suffix, and an icon vocabulary is a nested object whose property paths
    are the labels.

    Args:
        found: The validated inventory of the current pin.
        approved: The family's approved descriptor, empty before first approval.
        name: The constructor name being rebound.
        since: Schema version that introduced the binding.
        index: The pin's opt-in index; a member that needs a marker carries it.

    Returns:
        The proposal, or None when the name is not one of these vocabularies.
    """
    if name in MEMBERS:
        owner, prefix, also_from = MEMBERS[name]
        return propose_members(
            found,
            owner,
            approved,
            since=since,
            prefix=prefix,
            opt_ins=index,
            also_from=also_from,
        )
    if name in EXTENSIONS:
        return propose_extension(
            found, EXTENSIONS[name], "kotlin/Float", approved, since=since
        )
    if name in ICONS:
        return propose_icons(found, ICONS[name], approved, since=since)
    source = approved.get("source") or {}
    if approved.get("kind") == "constant" and "members" in source:
        # A family read off its own holder's members, derived from the pin
        # (``constant_families``) rather than named in the tables above.
        return propose_members(
            found, source["owner"], approved, since=since, opt_ins=index
        )
    return None


def bind(
    found: Inventory,
    evidence: dict[tuple[str, str, str], dict[str, Any]],
    registry: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    """Propose one approved binding against the current pin, or explain the refusal."""
    approved = registry["valueTypes"].get(name, {})
    since = approved.get("since", registry["schemaVersion"])
    index = opt_in_index(found)
    try:
        proposal = propose_vocabulary(found, approved, name, since=since, index=index)
        if proposal is not None:
            return {"name": name, "proposal": proposal}
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
                    (source.owner, source.jvm_name or "", source.jvm_descriptor or "")
                ),
                role=approved.get("kind"),
                approved_family=approved.get("family"),
                surface=tuple(approved["parameters"])
                if "parameters" in approved
                else None,
                opt_ins=index,
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
