"""Check approved bindings against the pinned inventory, never AndroidX main."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema.classpath_dump import DUMP_DIR, Inventory, inventory, source_defaults
from schema.propose import refresh

DERIVED = ("source", "kotlinType", "native", "omitted")
"""Fields the pinned compiler alone decides; approved policy only adds."""
DRIFT = "pinned proposal differs from approved binding; review before applying"


def _derived(spec: dict[str, Any]) -> dict[str, Any]:
    """Reduce a descriptor to facts the compiler decides, ignoring approved bounds."""
    return {
        **{key: spec[key] for key in DERIVED if key in spec},
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
    """Packages the pin declares for one composable name.

    A name can also appear as a parameterless extension declaration in packages
    like semantics or content; those are not components, so declarations that
    state parameters of their own decide the answer.

    Args:
        found: The validated pinned inventory.
        name: The component's schema name.

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


def compare(registry: dict[str, Any], found: Inventory) -> list[str]:
    """Report removed props and moved packages without merging overloads."""
    errors = []
    for name, entry in registry["components"].items():
        overloads = [
            d
            for d in found.declarations
            if d.name == name and d.disposition in {"ui", "support"}
        ]
        if not overloads:
            errors.append(f"{name}: no public composable in the pinned inventory")
            continue
        packages = pinned_packages(found, name)
        if entry.get("package") not in packages:
            errors.append(
                f"{name}: package {entry.get('package')!r} is not pinned "
                f"({', '.join(sorted(packages))})"
            )
        names = {p.name for d in overloads for p in d.parameters}
        removed = entry["props"].keys() - set(entry.get("reshaped", [])) - names
        errors.extend(
            f"{name}.{prop}: no parameter in any pinned overload" for prop in removed
        )
        errors.extend(provider_errors(name, entry, overloads))
    return errors


def compare_values(
    registry: dict[str, Any], found: Inventory, evidence: dict
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DUMP_DIR)
    parser.add_argument("--schema", type=Path, default=Path("schema/components.json"))
    args = parser.parse_args(argv)
    try:
        registry = json.loads(args.schema.read_text())
        found = inventory(args.directory)
        errors = compare(registry, found) + compare_values(
            registry, found, source_defaults(args.directory)
        )
        for error in errors:
            print(error, file=sys.stderr)
        return int(bool(errors))
    except (OSError, ValueError) as exc:
        print(f"check_upstream.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
