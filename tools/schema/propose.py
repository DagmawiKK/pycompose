"""Propose value bindings from the pinned inventory; never edit the approved schema.

Run ``./gradlew dumpComposeDefaults`` in android/ first, then e.g.
``python tools/schema/propose.py Dp buttonElevation --out proposal.json``.
Every overload is retained or reported with an explicit refusal.
"""

from __future__ import annotations

import argparse
import json
import sys
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
POLICIES = {
    "androidx/compose/ui/unit/Dp": {"minimum": 0},
    "androidx/compose/ui/geometry/Size": {"minimum": 0},
    "androidx/compose/foundation/layout/PaddingValues": {"minimum": 0},
    "androidx/compose/foundation/layout/WindowInsets": {"minimum": 0},
}
"""Small reusable per-family rules. Anything else is reported, never guessed."""


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
        "descriptor": source.jvm_descriptor,
    }


def propose_value(
    source: Declaration,
    *,
    since: str,
    families: dict[str, str],
    defaults: dict[str, Any] | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    """Derive an ordinary constructor/factory using reusable type/default policies.

    Args:
        source: The exact pinned declaration to bind.
        since: Schema version that introduced the binding.
        families: Native classifier to wire family, for already-bound families.
        defaults: Compiler-resolved defaults keyed by JVM identity, when known.
        role: An approved wire role to preserve instead of re-deriving.

    Returns:
        A value descriptor that is a drop-in candidate for ``valueTypes``.

    Raises:
        ValueError: The declaration needs a policy a proposal must not invent.
    """
    if source.disposition != "support" or source.receiver or source.context_receivers:
        raise ValueError("not a public, receiver-free value callable")
    if source.document.get("declarationKind") not in {"function", "constructor"}:
        raise ValueError("not a constructor or factory")
    if source.dispatch_receiver and source.document.get("classKind") != "OBJECT":
        raise ValueError("instance methods need an explicit native receiver protocol")
    if source.return_type.nullable or source.return_type.arguments:
        raise ValueError("nullable/generic return needs an explicit value policy")
    native_type = source.return_type.classifier.replace("/", ".")
    if native_type.startswith("kotlin."):
        raise ValueError("not a native value family")
    family = families.get(source.return_type.classifier, native_type.rsplit(".", 1)[-1])
    parameters = {}
    for parameter in source.parameters:
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
    constructor = source.document["declarationKind"] == "constructor"
    owner = (
        source.owner.replace("$", ".") if source.dispatch_receiver else source.package
    )
    call = native_type if constructor else owner + "." + source.name
    return {
        "family": family,
        "kind": _role(constructor, parameters, role),
        "kotlinType": native_type,
        "since": since,
        "source": identity(source),
        "parameters": parameters,
        "native": {"call": call},
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
    exact = [d for d in callables if identity(d, pinned=False) == wanted]
    if exact:
        return exact
    return [
        d
        for d in callables
        if identity(d, pinned=False)["owner"] == approved["owner"]
        and d.name == approved["name"]
    ]


def bind(
    found: Inventory,
    evidence: dict[tuple[str, str, str], dict[str, Any]],
    registry: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    """Propose one approved binding against the current pin, or explain the refusal."""
    approved = registry["valueTypes"].get(name, {})
    families = {
        s["kotlinType"].replace(".", "/"): s["family"]
        for s in registry["valueTypes"].values()
        if "family" in s
    }
    matches = select(found, approved.get("source"), name)
    if not matches:
        return {"name": name, "unsupported": "no public value callable at this pin"}
    proposals = []
    for source in matches:
        item: dict[str, Any] = {"name": name, "source": identity(source)}
        try:
            item["proposal"] = propose_value(
                source,
                since=approved.get("since", registry["schemaVersion"]),
                families=families,
                defaults=evidence.get(
                    (source.owner, source.jvm_name, source.jvm_descriptor)
                ),
                role=approved.get("kind"),
            )
        except ValueError as exc:
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


def refresh(
    found: Inventory,
    evidence: dict[tuple[str, str, str], dict[str, Any]],
    registry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Rebind every approved binding, naming those still maintained by hand."""
    results = []
    for name, spec in registry["valueTypes"].items():
        if "family" not in spec:
            continue
        if "source" not in spec:
            results.append({"name": name, "handwritten": True})
            continue
        results.append(bind(found, evidence, registry, name))
    return results


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
