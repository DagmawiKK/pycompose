"""Plan every exact UI overload without changing the approved catalog.

    python tools/schema/components.py --out android/build/compose-api/components.json

Plans are development evidence, not component registry entries. Native call plans
must still be integrated with IR slots/context and validated before approval.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pycompose.contract.registry_vocabulary import (
    HOST_VALUES,
    RESOURCE_TYPES,
    STATE_HOLDERS,
    TRANSIENT_HOLDERS,
)
from pycompose_codegen.checkout import PACKAGE, ROOT
from pycompose_codegen.derive.classpath_dump import (
    DUMP_DIR,
    Declaration,
    Inventory,
    Kind,
    Parameter,
    inventory,
    source_defaults,
)
from pycompose_codegen.derive.classpath_types import KotlinType
from pycompose_codegen.derive.keyed import KEY, is_keyed
from pycompose_codegen.derive.opt_ins import OptInIndex, opt_in_index
from pycompose_codegen.derive.property_holders import property_holders
from pycompose_codegen.derive.propose import (
    SCALARS,
    identity,
    source_name,
    value_families,
)
from pycompose_codegen.derive.resolution import MODIFIER, block_unaddressable_overloads
from pycompose_codegen.derive.slots import (
    builder_rule,
    function_arguments,
    scope_providers,
    slot_rule,
    slot_scopes,
)
from pycompose_codegen.emit.defaults import render_default

HOLDER_KINDS = {holder: kind for kind, holder in STATE_HOLDERS.items()}
TRANSIENT_BY_HOLDER = {holder: kind for kind, holder in TRANSIENT_HOLDERS.items()}


def _binding_rule(
    parameter: Parameter,
    families: dict[str, str],
    defaults: dict[str, Any],
    holders: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Decide how one native parameter reaches the wire, never by its name."""
    value = parameter.type
    if parameter.vararg_type:
        raise ValueError("varargs need a collection binding")
    if value.classifier == KEY:
        return {"policy": "key"}  # keyed content's value, as its wire key
    if value.classifier == MODIFIER and not value.nullable:
        if parameter.has_default and defaults.get(parameter.name) != {
            "kind": "object",
            "symbol": "androidx.compose.ui.Modifier.Companion",
        }:
            raise ValueError("modifier default is not the native identity")
        return {"policy": "modifier"}
    if parameter.kind == Kind.SLOT:
        rule = slot_rule(value)
    elif parameter.kind == Kind.BUILDER:
        rule = builder_rule(value)
    elif parameter.kind == Kind.CALLBACK:
        arguments = function_arguments(value)
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
    elif (typed := _host_filled(parameter, holders)) is not None:
        rule = typed
    elif value.classifier in SCALARS and not value.arguments:
        rule = {"policy": "scalar", "wireType": SCALARS[value.classifier]}
    elif source_name(value.classifier) in families and not value.arguments:
        rule = {"policy": "value", "family": families[source_name(value.classifier)]}
    else:
        raise ValueError(f"no wire policy for {value.classifier}")
    return rule


def _holder(
    value: KotlinType, holders: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """A holder a family fills: a hand-written one, or one the pin derives."""
    if value.nullable:
        return None
    if (kind := HOLDER_KINDS.get(source_name(value.classifier))) is not None:
        return {"policy": "holder", "kind": kind}
    if value.classifier in holders:
        return {"policy": "holder", "kind": "properties", **holders[value.classifier]}
    return None


def _host_filled(
    parameter: Parameter, holders: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Rule for a type the host fills: a late read, a holder, a resource or a value."""
    value = parameter.type
    name = source_name(value.classifier)
    if parameter.kind == Kind.PROVIDER:
        returns = value.arguments[-1][1]
        if returns is None or returns.nullable or returns.classifier not in SCALARS:
            raise ValueError("synchronous result needs a provider/predicate protocol")
        return {"policy": "provider", "wireType": SCALARS[returns.classifier]}
    if (holder := _holder(value, holders)) is not None:
        return holder
    if name in TRANSIENT_BY_HOLDER and not value.nullable:
        return {"policy": "transient", "kind": TRANSIENT_BY_HOLDER[name]}
    if name in HOST_VALUES and not value.nullable:
        prop, spec = HOST_VALUES[name]
        return {"policy": "hostValue", "prop": prop, "spec": spec}
    if name in RESOURCE_TYPES and not value.arguments:
        decoder, kinds = RESOURCE_TYPES[name]
        return {"policy": "resource", "decode": decoder, "values": list(kinds)}
    return None


def bind_parameter(
    parameter: Parameter,
    families: dict[str, str],
    defaults: dict[str, Any],
    holders: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Decide how one native parameter reaches the wire, with its default.

    Args:
        parameter: The pinned parameter.
        families: Approved value families, by the classifier they bind.
        defaults: The declaration's compiler-resolved defaults, by parameter.
        holders: Holders the pin derives a family for (``property_holders``).

    Returns:
        The parameter's rule.

    Raises:
        ValueError: The parameter has no wire policy, or an unusable default.
    """
    rule = _binding_rule(parameter, families, defaults, holders)
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
        empty = expression.get("kind") == "emptyLambda" or (
            expression == {**expression, "kind": "literal", "value": None}
            and parameter.type.nullable
        )
        if rule["policy"] == "slot" and not empty:
            # Absence renders null or an empty lambda; any other default needs
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
    holders: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Plan one exact overload, recording every capability it would need.

    A member of an ``object`` (``SearchBarDefaults.InputField``) is called
    through the object; a member of a scope (``ExposedDropdownMenu``) composes
    inside it, as an extension on it does.
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
        or (source.document.get("typeParameters") and not is_keyed(source))
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
            rule = bind_parameter(parameter, families, defaults, holders or {})
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
    providers = scope_providers((d for d in found.declarations if d.composable), scopes)
    objects = frozenset(c.classifier for c in found.classes if c.class_kind == "OBJECT")
    holders = property_holders(found, defaults)
    candidates = [
        _plan(
            source,
            families,
            defaults.get((source.owner, source.jvm_name, source.jvm_descriptor), {}),
            default_markers,
            providers,
            index,
            objects,
            scopes,
            holders,
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
    protected = {
        args.schema.resolve(),
        (ROOT / "schema/catalog.lock.json").resolve(),
        (PACKAGE / "contract/catalog.lock.json").resolve(),
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
