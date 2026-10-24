"""Check what the lock keeps by policy against the pin, never AndroidX main.

``composegen generate`` runs these: every component's binding against its one
selected pinned overload (a held entry's props, providers and scopes included)
and every value family's descriptor against the derivation the pin implies.
The holders section needs no check -- the compiler derives it.
"""

from __future__ import annotations

from typing import Any

from pycompose.compiler.candidate_props import scope_for
from pycompose.compiler.classpath_dump import Inventory
from pycompose.compiler.component_binding import resolutions, unversioned
from pycompose.compiler.propose import refresh

DERIVED = ("source", "kotlinType", "native", "omitted")
"""Fields the pinned compiler alone decides; approved policy only adds."""
DRIFT = "pinned proposal differs from approved binding; review before applying"


def _derived(spec: dict[str, Any]) -> dict[str, Any]:
    """Reduce a descriptor to facts the compiler decides, ignoring approved bounds."""
    facts = {key: spec[key] for key in DERIVED if key in spec}
    if "source" in facts:
        facts["source"] = unversioned(facts["source"])
    return {
        **facts,
        "parameters": {
            field: {
                key: rule[key]
                for key in (
                    "type",
                    "valueType",
                    "required",
                    "nullable",
                    "default",
                    "items",
                    "values",
                )
                if key in rule
            }
            for field, rule in spec["parameters"].items()
        },
    }


def pinned_packages(found: Inventory, name: str) -> set[str]:
    """Packages the pin declares for one native composable name.

    A name can also appear as a parameterless extension declaration in packages
    like semantics or content; those are not components, so declarations that
    state parameters of their own decide the answer.

    Args:
        found: The validated pinned inventory.
        name: The component's native name.

    Returns:
        Every package a component of that name is pinned in.
    """
    declarations = [
        d
        for d in found.declarations
        if d.name == name and d.disposition in {"ui", "support"}
    ]
    with_parameters = [d for d in declarations if d.parameters]
    return {d.package for d in (with_parameters or declarations)}


def provider_errors(
    name: str, entry: dict[str, Any], overloads: list[Any]
) -> list[str]:
    """Re-derive every provider parameter from the pin.

    A provider names a native parameter and the return type of the lambda the
    host supplies, so both facts can be checked against the same overloads the
    rest of the entry is checked against.

    Args:
        name: The component's schema name.
        entry: Its approved schema entry.
        overloads: The pinned declarations carrying that name.

    Returns:
        One message per provider whose parameter or return type is not pinned.
    """
    errors = []
    for prop, spec in entry["props"].items():
        provider = spec.get("provider")
        if provider is None:
            continue
        returns = {
            argument[1].classifier.rsplit("/", 1)[-1]
            for declaration in overloads
            for parameter in declaration.parameters
            if parameter.name == provider["native"]
            and parameter.type.classifier == "kotlin/Function0"
            for argument in parameter.type.arguments
        }
        if not returns:
            errors.append(
                f"{name}.{prop}: provider parameter {provider['native']!r} "
                "is not a pinned zero-arg function"
            )
        elif provider["returns"] not in returns:
            errors.append(
                f"{name}.{prop}: provider returns {provider['returns']!r} is not "
                f"pinned ({', '.join(sorted(returns))})"
            )
    return errors


def _content_scope(declaration: Any, native: str) -> str | None:
    """The approved composition scope one pinned content lambda carries.

    Args:
        declaration: One pinned declaration.
        native: The parameter the children compose into.

    Returns:
        The scope's schema name, or None when the lambda carries none.
    """
    for parameter in declaration.parameters:
        if parameter.name != native:
            continue
        if "kotlin/ExtensionFunctionType" not in parameter.type.annotations:
            continue
        arguments = [type_ for _, type_ in parameter.type.arguments]
        # Children compose in a receiver-only lambda: one that also passes an
        # argument (a key, an item) is another protocol's.
        if len(arguments) != 2 or arguments[0] is None:
            continue
        return scope_for(arguments[0].classifier)
    return None


def scope_errors(name: str, entry: dict[str, Any], overloads: list[Any]) -> list[str]:
    """Re-derive a component's receiver and the scope it hands to its children.

    A component the pin declares as an extension on a composition scope composes
    only inside a parent that provides the receiver, and a parent's content
    lambda carries its receiver exactly when the pin says it does. Both are
    facts about the pinned declarations, so both are checked against them: a
    release that drops a receiver, or adds one, must not pass silently.

    Args:
        name: The component's schema name.
        entry: Its approved schema entry.
        overloads: The pinned declarations carrying that name.

    Returns:
        One message per scope fact that no longer matches the pin.
    """
    errors = []
    with_parameters = [d for d in overloads if d.parameters]
    declared = entry.get("scope")
    if declared is not None:
        if not any(
            (receiver := d.receiver or d.dispatch_receiver) is not None
            and scope_for(receiver.classifier) == declared
            for d in with_parameters
        ):
            errors.append(
                f"{name}: scope {declared!r} is not a pinned declaration's receiver"
            )
    elif with_parameters and all(d.receiver is not None for d in with_parameters):
        errors.append(
            f"{name}: every pinned overload is a scope extension; declare 'scope'"
        )

    children = entry.get("children", {})
    native = children.get("native", "content")
    with_content = [
        d for d in with_parameters if any(p.name == native for p in d.parameters)
    ]
    provides = children.get("provides")
    if provides is not None:
        scopes = {_content_scope(d, native) for d in with_content}
        if provides not in scopes:
            errors.append(
                f"{name}: children.provides {provides!r} is not the pinned "
                "content lambda's receiver"
            )
    elif (
        children.get("allowed")
        and children.get("kind") != "items"
        and with_content
        and all(_content_scope(d, native) is not None for d in with_content)
    ):
        found = sorted(
            {scope for d in with_content if (scope := _content_scope(d, native))}
        )
        errors.append(
            f"{name}: pinned content composes under {', '.join(found)}; "
            "declare children.provides"
        )
    return errors


def compare(registry: dict[str, Any], found: Inventory) -> list[str]:
    """Report component drift against one selected pinned overload each.

    Every entry is resolved to a single overload first -- a union of parameter
    names across siblings cannot tell one signature from another, and a prop
    that only a sibling declares used to pass. The selected identity must match
    the recorded ``source``; a hand-written adapter keeps the union boundary
    and says so by claiming no identity.

    Args:
        registry: The approved catalog.
        found: The validated inventory of the current pin.

    Returns:
        One message per fact that no longer matches the pin.
    """
    errors = []
    resolved = {result.name: result for result in resolutions(registry, found)}
    for name, entry in registry["components"].items():
        source = entry.get("source")
        native = source.get("name", name) if isinstance(source, dict) else name
        overloads = [
            d
            for d in found.declarations
            if d.name == native and d.disposition in {"ui", "support"}
        ]
        if not overloads:
            errors.append(f"{name}: no public composable in the pinned inventory")
            continue
        packages = pinned_packages(found, native)
        if entry.get("package") not in packages:
            errors.append(
                f"{name}: package {entry.get('package')!r} is not pinned "
                f"({', '.join(sorted(packages))})"
            )
            # Resolution is meaningless against a package the pin never
            # declares; every name-level message would only restate this.
            continue
        errors.extend(provider_errors(name, entry, overloads))
        errors.extend(scope_errors(name, entry, overloads))
        resolution = resolved[name]
        errors.extend(resolution.errors)
        errors.extend(resolution.differences)
        if resolution.mode == "manual":
            names = {p.name for d in overloads for p in d.parameters}
            removed = entry["props"].keys() - set(entry.get("reshaped", [])) - names
            errors.extend(
                f"{name}.{prop}: no parameter in any pinned overload"
                for prop in removed
            )
    return errors


def compare_values(
    registry: dict[str, Any], found: Inventory, evidence: dict[Any, Any]
) -> list[str]:
    """Re-derive every binding the same way ``--refresh`` does, and compare.

    Sharing one derivation is deliberate: a drift check that re-implements the
    proposal rules would disagree with the proposer at exactly the moment a
    release changes something.

    Args:
        registry: The approved catalog.
        found: The validated inventory of the current pin.
        evidence: Compiler-resolved defaults keyed by JVM identity.

    Returns:
        One message per binding whose pinned derivation no longer matches.
    """
    errors = []
    for item in refresh(found, evidence, registry):
        name = item["name"]
        spec = registry["valueTypes"][name]
        if "source" not in spec:
            continue  # Explicit policy is reviewed, not re-derived.
        if "proposal" not in item:
            errors.append(f"{name}: {item.get('unsupported', 'no proposal')}")
            continue
        if _derived(item["proposal"]) != _derived(spec):
            errors.append(f"{name}: {DRIFT}")
    return errors
