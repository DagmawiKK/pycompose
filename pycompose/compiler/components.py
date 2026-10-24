"""Plan every exact UI overload without changing the approved catalog.

    python tools/schema/components.py --out android/build/compose-api/components.json

Plans are development evidence, not component registry entries. Native call plans
must still be integrated with IR slots/context and validated before approval.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from pycompose.compiler.classpath_dump import (
    DUMP_DIR,
    Declaration,
    Inventory,
    Kind,
    Parameter,
    inventory,
    source_defaults,
)
from pycompose.compiler.classpath_types import KotlinType
from pycompose.compiler.opt_ins import OptInIndex, opt_in_index
from pycompose.compiler.propose import SCALARS, identity, source_name, value_families
from pycompose.compiler.resolution import MODIFIER, block_unaddressable_overloads
from pycompose.core.registry_vocabulary import (
    HOST_VALUES,
    RESOURCE_TYPES,
    STATE_HOLDERS,
    TRANSIENT_HOLDERS,
)
from pycompose.schema.codegen.defaults import render_default

HOLDER_KINDS = {holder: kind for kind, holder in STATE_HOLDERS.items()}
TRANSIENT_BY_HOLDER = {holder: kind for kind, holder in TRANSIENT_HOLDERS.items()}


def _function(value: KotlinType) -> list[KotlinType]:
    """Return the synchronous arguments a native function type receives."""
    if (
        value.suspend
        or not value.arguments
        or any(t is None for _, t in value.arguments)
    ):
        raise ValueError("unresolved/suspending function needs a native protocol")
    arguments = [t for _, t in value.arguments if t is not None]
    if arguments[-1].classifier != "kotlin/Unit" or arguments[-1].nullable:
        raise ValueError("synchronous result needs a provider/predicate protocol")
    return arguments[:-1]


CONSUMED = {"androidx/compose/foundation/layout/PaddingValues": "paddingValues"}
"""Slot arguments the adapter applies on the subtree's behalf (``CONSUMERS``)."""

LAZY_LIST = "androidx/compose/foundation/lazy/LazyListScope"


def _slot(value: KotlinType) -> dict[str, Any]:
    """Classify a composable lambda as a scoped, unscoped or consuming slot.

    A receiver the lambda carries is handed to the children, so a child that
    composes only inside it can (ADR-0016 decision 1); one that needs none
    composes as it would anywhere.
    """
    arguments = _function(value)
    receiver = None
    if "kotlin/ExtensionFunctionType" in value.annotations:
        if not arguments:
            raise ValueError("missing slot receiver")
        native_receiver = arguments.pop(0)
        if native_receiver.nullable or native_receiver.arguments:
            raise ValueError(
                f"slot scope needs a native protocol: {native_receiver.classifier}"
            )
        receiver = native_receiver.classifier
    rule: dict[str, Any] = {"policy": "slot", "receiver": receiver}
    if (
        len(arguments) == 1
        and not arguments[0].nullable
        and arguments[0].classifier in CONSUMED
    ):
        rule["consume"] = CONSUMED[arguments[0].classifier]
    elif arguments:
        raise ValueError("slot-supplied arguments need typed context references")
    return rule


def _builder(value: KotlinType) -> dict[str, Any]:
    """A lazy list's builder lambda: the children are the items it lists."""
    receiver = value.arguments[0][1]
    if receiver is None or receiver.classifier != LAZY_LIST or receiver.nullable:
        named = receiver.classifier if receiver is not None else "unresolved"
        raise ValueError(f"builder scope needs a native protocol: {named}")
    return {"policy": "slot", "receiver": None, "kind": "items"}


def _binding_rule(
    parameter: Parameter, families: dict[str, str], defaults: dict[str, Any]
) -> dict[str, Any]:
    """Decide how one native parameter reaches the wire, never by its name."""
    value = parameter.type
    if parameter.vararg_type:
        raise ValueError("varargs need a collection binding")
    if value.classifier == MODIFIER and not value.nullable:
        if parameter.has_default and defaults.get(parameter.name) != {
            "kind": "object",
            "symbol": "androidx.compose.ui.Modifier.Companion",
        }:
            raise ValueError("modifier default is not the native identity")
        return {"policy": "modifier"}
    if parameter.kind == Kind.SLOT:
        rule = _slot(value)
    elif parameter.kind == Kind.BUILDER:
        rule = _builder(value)
    elif parameter.kind == Kind.CALLBACK:
        arguments = _function(value)
        if any(t.classifier not in SCALARS for t in arguments):
            raise ValueError("event payload needs a structured value codec")
        rule = {
            "policy": "event",
            "payload": [
                {
                    "name": f"arg{i}",
                    "type": SCALARS[t.classifier],
                    "nullable": t.nullable,
                }
                for i, t in enumerate(arguments)
            ],
        }
    elif (typed := _host_filled(parameter)) is not None:
        rule = typed
    elif value.classifier in SCALARS and not value.arguments:
        rule = {"policy": "scalar", "wireType": SCALARS[value.classifier]}
    elif source_name(value.classifier) in families and not value.arguments:
        rule = {"policy": "value", "family": families[source_name(value.classifier)]}
    else:
        raise ValueError(f"no wire policy for {value.classifier}")
    return rule


def _host_filled(parameter: Parameter) -> dict[str, Any] | None:
    """Rule for a type the host fills: a late read, a holder, a resource or a value."""
    value = parameter.type
    name = source_name(value.classifier)
    if parameter.kind == Kind.PROVIDER:
        returns = value.arguments[-1][1]
        if returns is None or returns.nullable or returns.classifier not in SCALARS:
            raise ValueError("synchronous result needs a provider/predicate protocol")
        return {"policy": "provider", "wireType": SCALARS[returns.classifier]}
    if name in HOLDER_KINDS and not value.nullable:
        return {"policy": "holder", "kind": HOLDER_KINDS[name]}
    if name in TRANSIENT_BY_HOLDER and not value.nullable:
        return {"policy": "transient", "kind": TRANSIENT_BY_HOLDER[name]}
    if name in HOST_VALUES and not value.nullable:
        prop, spec = HOST_VALUES[name]
        return {"policy": "hostValue", "prop": prop, "spec": spec}
    if name in RESOURCE_TYPES and not value.arguments:
        decoder, kinds = RESOURCE_TYPES[name]
        return {"policy": "resource", "decode": decoder, "values": list(kinds)}
    return None


def _parameter(
    parameter: Parameter, families: dict[str, str], defaults: dict[str, Any]
) -> dict[str, Any]:
    """Attach the compiler-resolved default an optional parameter binds to."""
    rule = _binding_rule(parameter, families, defaults)
    if rule["policy"] in {"modifier", "holder", "transient", "hostValue"}:
        # The host supplies both: the wire never carries their defaults.
        return rule
    if parameter.has_default:
        if parameter.name not in defaults:
            raise ValueError("missing compiler-resolved default")
        expression = defaults[parameter.name]
        if expression.get("kind") == "unsupported":
            raise ValueError("default: " + expression["reason"])
        render_default(expression, set())
        if rule["policy"] == "slot" and (
            expression.get("kind") != "literal"
            or expression.get("value") is not None
            or not parameter.type.nullable
        ):
            # Only an absent/null slot default is renderable. Anything else needs
            # a native protocol and would silently change what renders.
            raise ValueError("optional slot needs an explicit null policy")
        rule["default"] = expression
    return rule


def _symbols(expression: dict[str, Any]) -> Iterator[str]:
    """Yield every native symbol one default expression names."""
    if "symbol" in expression:
        yield expression["symbol"]
    if "receiver" in expression:
        yield from _symbols(expression["receiver"])


def _scope_providers(
    declarations: Iterable[Declaration], scopes: frozenset[str]
) -> set[str]:
    """Classifiers an app composes *inside*, not merely passes as a parameter.

    A builder's own receiver, or a slot lambda's (``scopes``); members of any
    other type reach an app only as parameters (ADR-0016 decision 1).
    """
    return {d.receiver.classifier for d in declarations if d.receiver} | scopes


def slot_scopes(declarations: Iterable[Declaration]) -> frozenset[str]:
    """Receivers a pinned slot lambda carries: the only ones a host can hand down.

    A declaration on one, or in one, has a parent to compose inside.
    """
    return frozenset(
        receiver.classifier
        for declaration in declarations
        if declaration.composable
        for parameter in declaration.parameters
        if "androidx/compose/runtime/Composable" in parameter.type.annotations
        and "kotlin/ExtensionFunctionType" in parameter.type.annotations
        and parameter.type.arguments
        and (receiver := parameter.type.arguments[0][1]) is not None
        and not receiver.nullable
        and not receiver.arguments
    )


def _surface(source: Declaration, scope_providers: set[str]) -> str:
    """Report whether an app composes a declaration or only passes it in.

    Member composables of `*Defaults` objects and similar carriers
    (`SliderDefaults.Thumb`, `TextFieldDefaults.Container`) are styling hooks:
    parameter support for the component that consumes them, never entries in the
    component denominator. Members of a provided scope (`ExposedDropdownMenu`
    inside `ExposedDropdownMenuBoxScope`) are scope-bound components.
    """
    receiver = source.dispatch_receiver
    if receiver is not None and receiver.classifier not in scope_providers:
        return "hook"
    return "component"


def _plan(
    source: Declaration,
    families: dict[str, str],
    defaults: dict[str, Any],
    default_markers: dict[str, set[str]],
    scope_providers: set[str],
    index: OptInIndex,
    objects: frozenset[str] = frozenset(),
    scopes: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Plan one exact overload, recording every capability it would need.

    A member of an ``object`` (``SearchBarDefaults.InputField``) is called
    through the object, so its dispatch receiver needs no protocol. A member of
    a scope (``ExposedDropdownMenu``) composes inside it, as an extension on it
    does: that receiver is the plan's.
    """
    parameters: dict[str, Any] = {}
    gaps = []
    holder = source.dispatch_receiver
    static = holder is not None and holder.classifier.replace("/", ".") in objects
    member = holder is not None and not static and source.receiver is None
    receiver = holder if member else source.receiver
    if (
        (receiver is not None and receiver.classifier not in scopes)
        or (holder and not static and not member)
        or source.context_receivers
        or source.document.get("typeParameters")
    ):
        gaps.append(
            {
                "parameter": None,
                "required": True,
                "reason": "receiver/generic declaration needs a native protocol",
            }
        )
    for parameter in source.parameters:
        try:
            rule = _parameter(parameter, families, defaults)
        except ValueError as exc:
            rule = {"policy": "blocked" if parameter.required else "omit"}
            gaps.append(
                {
                    "parameter": parameter.name,
                    "required": parameter.required,
                    "reason": str(exc),
                }
            )
        parameters[parameter.name] = {
            **rule,
            "type": parameter.type.document,
            "required": parameter.required,
            "hasDefault": parameter.has_default,
        }
    opt_ins = index.of(source)
    for spec in parameters.values():
        for symbol in _symbols(spec.get("default", {})):
            opt_ins.update(default_markers.get(symbol, set()))
    inaccessible = sorted(opt_ins & index.inaccessible)
    if inaccessible:
        gaps.append(
            {
                "parameter": None,
                "required": True,
                "reason": (
                    "opt-in marker is not accessible outside the pin: "
                    + ", ".join(inaccessible)
                ),
            }
        )
    return {
        "name": source.name,
        "surface": _surface(source, scope_providers),
        "source": identity(source),
        "call": (source.owner.replace("$", ".") if static else source.package)
        + "."
        + source.name,
        "annotations": source.annotations,
        "parameters": parameters,
        "receiver": receiver.document if receiver else None,
        "optIn": sorted(opt_ins),
        "dependencies": {
            "values": sorted(
                {p["family"] for p in parameters.values() if p["policy"] == "value"}
            ),
            "scopes": sorted(
                {
                    p["receiver"]
                    for p in parameters.values()
                    if p["policy"] == "slot" and p["receiver"]
                }
                | ({receiver.classifier} if receiver else set())
            ),
        },
        "gaps": gaps,
        "status": "blocked" if any(g["required"] for g in gaps) else "call-plan",
        "approval": "required",
        "verification": {
            "compiled": False,
            "rendered": False,
            "stateControlled": False,
        },
        "integrationGaps": [
            "IR/schema approval and compatibility",
            "named slot transport and scoped rendering context",
            "generated registry and Python constructors",
            "per-app dependency closure and behavioral verification",
        ],
    }


def _worklist(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group recorded gaps by the capability that would close them.

    Each reason lists the components it blocks, the hooks it blocks (styling
    hooks are parameter support, so their gaps never read as component
    blockers), and the names it only limits — so capabilities can be added in
    one deliberate batch instead of overload by overload.
    """
    blocking: dict[str, set[str]] = defaultdict(set)
    hooks: dict[str, set[str]] = defaultdict(set)
    limiting: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        for gap in candidate["gaps"]:
            if not gap["required"]:
                limiting[gap["reason"]].add(candidate["name"])
            elif candidate["surface"] == "hook":
                hooks[gap["reason"]].add(candidate["name"])
            else:
                blocking[gap["reason"]].add(candidate["name"])
    return [
        {
            "reason": reason,
            "blocks": sorted(blocking[reason]),
            "hooks": sorted(hooks[reason]),
            "limits": sorted(limiting[reason]),
        }
        for reason in sorted(blocking.keys() | hooks.keys() | limiting.keys())
    ]


def _surface_coverage(candidates: list[dict[str, Any]], surface: str) -> dict[str, int]:
    """Count what one surface offers, keeping hooks out of the component tally."""
    subset = [c for c in candidates if c["surface"] == surface]
    statuses = Counter(c["status"] for c in subset)
    return {
        "names": len({c["name"] for c in subset}),
        "overloads": len(subset),
        "callPlan": statuses["call-plan"],
        "blocked": statuses["blocked"],
    }


def propose_components(
    found: Inventory, defaults: dict[Any, Any], registry: dict[str, Any]
) -> dict[str, Any]:
    """Derive byte-stable, unapproved plans for all UI overloads in the inventory."""
    families = value_families(registry)
    index = opt_in_index(found)
    default_markers: dict[str, set[str]] = {}
    for declaration in found.declarations:
        holder = (
            declaration.owner.replace("$", ".")
            if declaration.dispatch_receiver
            else declaration.package
        )
        symbol = holder + "." + declaration.name
        default_markers.setdefault(symbol, set()).update(index.of(declaration))
    # Every representable argument is passed explicitly, so the arguments a call
    # carries are what Kotlin resolves on; overloads those arguments cannot tell
    # apart are refused rather than silently bound to a sibling.
    scopes = slot_scopes(found.declarations)
    scope_providers = _scope_providers(
        (d for d in found.declarations if d.composable), scopes
    )
    objects = frozenset(c.classifier for c in found.classes if c.class_kind == "OBJECT")
    candidates = [
        _plan(
            source,
            families,
            defaults.get((source.owner, source.jvm_name, source.jvm_descriptor), {}),
            default_markers,
            scope_providers,
            index,
            objects,
            scopes,
        )
        for source in sorted(
            found.ui,
            key=lambda d: (
                d.name,
                d.artifact,
                d.owner,
                d.jvm_name or "",
                d.jvm_descriptor or "",
            ),
        )
    ]
    policies = Counter(
        p["policy"] for c in candidates for p in c["parameters"].values()
    )
    block_unaddressable_overloads(candidates)
    return {
        "formatVersion": 1,
        "bom": found.bom,
        "compiler": found.compiler,
        "status": "proposal-only",
        "coverage": {
            "components": _surface_coverage(candidates, "component"),
            "hooks": _surface_coverage(candidates, "hook"),
            "enabled": 0,
            "compiled": 0,
        },
        "policies": dict(sorted(policies.items())),
        "worklist": _worklist(candidates),
        "candidates": candidates,
    }


def main() -> None:
    """Write a reviewable report, never a registry or generated component file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DUMP_DIR)
    parser.add_argument("--schema", type=Path, default=Path("schema/catalog.lock.json"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    protected = {
        args.schema.resolve(),
        (root / "schema/catalog.lock.json").resolve(),
        (root / "pycompose/schema/catalog.lock.json").resolve(),
    }
    if args.out and args.out.resolve() in protected:
        parser.error("a proposal cannot overwrite an approved schema")
    report = propose_components(
        inventory(args.inventory),
        source_defaults(args.inventory),
        json.loads(args.schema.read_text()),
    )
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.write_text(text)
    else:
        print(text, end="")
    if args.fail_on_blocked and any(
        p["status"] == "blocked" for p in report["candidates"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
