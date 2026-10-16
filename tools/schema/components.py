"""Plan every exact UI overload without changing the approved catalog.

    python tools/schema/components.py --out android/build/compose-api/components.json

Plans are development evidence, not component registry entries. Native call plans
must still be integrated with IR slots/context and validated before approval.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pycompose.core.registry_types import SCOPE_PATHS
from pycompose.schema.codegen.defaults import render_default
from schema.classpath_dump import (
    DUMP_DIR,
    Declaration,
    Inventory,
    Kind,
    Parameter,
    inventory,
    source_defaults,
)
from schema.propose import SCALARS, identity, source_name, value_families

# The pin reports receivers as classifier paths; derive that form from the
# closed scope vocabulary instead of transcribing it a second time.
SLASH_SCOPES = frozenset(path.replace(".", "/") for path in SCOPE_PATHS.values())
MODIFIER = "androidx/compose/ui/Modifier"


class DeclaredType(NamedTuple):
    """Kotlin type of a prop as overload selection compares it."""

    kind: str
    classifier: str
    nullable: bool
    composable: bool = False
    receiver: str = ""
    arity: int = 0


def _function(value) -> list[Any]:
    """Return the synchronous arguments a native function type receives."""
    if (
        value.suspend
        or not value.arguments
        or any(t is None for _, t in value.arguments)
    ):
        raise ValueError("unresolved/suspending function needs a native protocol")
    arguments = [t for _, t in value.arguments]
    if arguments[-1].classifier != "kotlin/Unit" or arguments[-1].nullable:
        raise ValueError("synchronous result needs a provider/predicate protocol")
    return arguments[:-1]


def _slot(value) -> dict[str, Any]:
    """Classify a composable lambda as a scoped or unscoped slot."""
    arguments = _function(value)
    receiver = None
    if "kotlin/ExtensionFunctionType" in value.annotations:
        if not arguments:
            raise ValueError("missing slot receiver")
        native_receiver = arguments.pop(0)
        receiver = native_receiver.classifier
        if (
            receiver not in SLASH_SCOPES
            or native_receiver.nullable
            or native_receiver.arguments
        ):
            raise ValueError(f"slot scope needs a native protocol: {receiver}")
    if arguments:
        raise ValueError("slot-supplied arguments need typed context references")
    return {"policy": "slot", "receiver": receiver}


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
    elif value.classifier in SCALARS and not value.arguments:
        rule = {"policy": "scalar", "wireType": SCALARS[value.classifier]}
    elif source_name(value.classifier) in families and not value.arguments:
        rule = {"policy": "value", "family": families[source_name(value.classifier)]}
    else:
        raise ValueError(f"no wire policy for {value.classifier}")
    return rule


def _parameter(
    parameter: Parameter, families: dict[str, str], defaults: dict[str, Any]
) -> dict[str, Any]:
    """Attach the compiler-resolved default an optional parameter binds to."""
    rule = _binding_rule(parameter, families, defaults)
    if rule["policy"] == "modifier":
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


def _opt_ins(annotations: list[str]) -> set[str]:
    """List the opt-in markers of one declaration's annotations."""
    return {
        a.replace("/", ".")
        for a in annotations
        if a.rsplit("/", 1)[-1].startswith("Experimental")
    }


def _scope_providers(declarations: Iterable[Declaration]) -> set[str]:
    """Classifiers an app composes *inside*, not merely passes as a parameter.

    A scope is provided by a composable that declares it as its own receiver (a
    scoped builder) or as the receiver of a composable lambda parameter
    (``content: FooScope.() -> Unit``). Members of such a type are composed by
    the app within its provider; members of any other type only reach an app as
    a parameter of the component that consumes them (ADR-0016 decision 1).
    """
    providers: set[str] = set()
    for declaration in declarations:
        if not declaration.composable:
            continue
        if declaration.receiver is not None:
            providers.add(declaration.receiver.classifier)
        for parameter in declaration.parameters:
            value = parameter.type
            if (
                "androidx/compose/runtime/Composable" in value.annotations
                and "kotlin/ExtensionFunctionType" in value.annotations
                and value.arguments
                and value.arguments[0][1] is not None
            ):
                providers.add(value.arguments[0][1].classifier)
    return providers


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
) -> dict[str, Any]:
    """Plan one exact overload, recording every capability it would need."""
    parameters: dict[str, Any] = {}
    gaps = []
    if (
        (source.receiver and source.receiver.classifier not in SLASH_SCOPES)
        or source.dispatch_receiver
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
    opt_ins = _opt_ins(source.annotations)
    for spec in parameters.values():
        for symbol in _symbols(spec.get("default", {})):
            opt_ins.update(default_markers.get(symbol, set()))
    return {
        "name": source.name,
        "surface": _surface(source, scope_providers),
        "source": identity(source),
        "call": source.package + "." + source.name,
        "annotations": source.annotations,
        "parameters": parameters,
        "receiver": source.receiver.document if source.receiver else None,
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
                | ({source.receiver.classifier} if source.receiver else set())
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


def _forwarded(candidate: dict[str, Any]) -> frozenset[str]:
    """Names a generated call passes, which is what Kotlin resolves on."""
    return frozenset(
        name
        for name, spec in candidate["parameters"].items()
        if spec["policy"] not in {"omit", "blocked"}
    )


def _declared_type(spec: dict[str, Any]) -> DeclaredType:
    """Describe the Kotlin type a prop declares, for overload selection."""
    doc = spec["type"]
    arguments = [a["type"] for a in doc["arguments"] if a["type"] is not None]
    if spec["policy"] in {"event", "slot"} or doc["classifier"].startswith(
        "kotlin/Function"
    ):
        receiver = ""
        if "kotlin/ExtensionFunctionType" in doc["annotations"] and arguments:
            receiver = arguments.pop(0)["classifier"]
        return DeclaredType(
            kind="function",
            classifier="kotlin/Function",
            nullable=doc["nullable"],
            composable="androidx/compose/runtime/Composable" in doc["annotations"],
            receiver=receiver,
            arity=len(arguments),
        )
    return DeclaredType(
        kind="value",
        classifier=MODIFIER if spec["policy"] == "modifier" else doc["classifier"],
        nullable=doc["nullable"],
    )


def _assignable(argument: DeclaredType, parameter: DeclaredType) -> bool:
    """Report whether the argument a call passes can bind that parameter."""
    if argument.kind != parameter.kind:
        return False
    if not (
        argument.nullable == parameter.nullable
        or (parameter.nullable and not argument.nullable)
    ):
        return False
    if argument.kind == "function":
        # A composable lambda is a distinct type kind, and arity/receiver must
        # match for the lambda to be accepted at all.
        return (argument.composable, argument.receiver, argument.arity) == (
            parameter.composable,
            parameter.receiver,
            parameter.arity,
        )
    return argument.classifier == parameter.classifier


def _competing(candidate: dict[str, Any], other: dict[str, Any]) -> bool:
    """Report whether a call carrying this overload's arguments could bind to ``other``.

    Kotlin applies ``other`` only when every argument it is given names one of its
    parameters, is type-compatible with it, and every required parameter it declares
    is among them. A parameter the call leaves unsupplied keeps the overload out of
    the candidate set, however similar the argument lists look.
    """
    mine = _forwarded(candidate)
    if not mine <= set(other["parameters"]):
        return False
    required = {name for name, spec in other["parameters"].items() if spec["required"]}
    if not required <= mine:
        return False
    return all(
        _assignable(
            _declared_type(candidate["parameters"][name]),
            _declared_type(other["parameters"][name]),
        )
        for name in mine
    )


def _block_unaddressable_overloads(candidates: list[dict[str, Any]]) -> None:
    """Refuse an overload no named-argument call can select uniquely.

    Two same-named overloads are only addressable when the arguments a call passes
    tell them apart. If a sibling accepts exactly the arguments this overload would
    pass, the recorded JVM identity is not what a compiler resolves to.
    """
    groups = defaultdict(list)
    for candidate in candidates:
        groups[candidate["call"]].append(candidate)
    for group in groups.values():
        if len(group) < 2:
            continue
        for candidate in group:
            if candidate["status"] != "call-plan":
                # Already refused for a capability this overload needs; a second
                # identity reason would not add information.
                continue
            if any(
                _competing(candidate, other)
                for other in group
                if other is not candidate
            ):
                candidate["gaps"].append(
                    {
                        "parameter": None,
                        "required": True,
                        "reason": (
                            "overload identity is not addressable by named arguments"
                        ),
                    }
                )
                candidate["status"] = "blocked"


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
    default_markers: dict[str, set[str]] = {}
    for declaration in found.declarations:
        holder = (
            declaration.owner.replace("$", ".")
            if declaration.dispatch_receiver
            else declaration.package
        )
        symbol = holder + "." + declaration.name
        default_markers.setdefault(symbol, set()).update(
            _opt_ins(declaration.annotations)
        )
    # Every representable argument is passed explicitly, so the arguments a call
    # carries are what Kotlin resolves on; overloads those arguments cannot tell
    # apart are refused rather than silently bound to a sibling.
    scope_providers = _scope_providers(found.declarations)
    candidates = [
        _plan(
            source,
            families,
            defaults.get((source.owner, source.jvm_name, source.jvm_descriptor), {}),
            default_markers,
            scope_providers,
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
    _block_unaddressable_overloads(candidates)
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
    parser.add_argument("--schema", type=Path, default=Path("schema/components.json"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    protected = {
        args.schema.resolve(),
        (root / "schema/components.json").resolve(),
        (root / "pycompose/schema/components.json").resolve(),
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
