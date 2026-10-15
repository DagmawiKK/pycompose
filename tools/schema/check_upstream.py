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


def compare(registry: dict[str, Any], found: Inventory) -> list[str]:
    """Report removed props without pretending different overloads are one binding."""
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
        names = {p.name for d in overloads for p in d.parameters}
        removed = entry["props"].keys() - set(entry.get("reshaped", [])) - names
        errors.extend(
            f"{name}.{prop}: no parameter in any pinned overload" for prop in removed
        )
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
