"""Check approved bindings against the pinned inventory, never AndroidX main."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema.classpath_dump import DUMP_DIR, Inventory, inventory, source_defaults
from schema.propose import identity, propose_value, select

DERIVED = ("source", "kotlinType", "native")
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
    """Check derived bindings; hand-maintained policy is reported, not judged."""
    errors = []
    values = {n: s for n, s in registry["valueTypes"].items() if "family" in s}
    families = {s["kotlinType"].replace(".", "/"): s["family"] for s in values.values()}
    for name, spec in values.items():
        if "source" not in spec:
            continue  # Legacy descriptors remain explicit policy, not derived coverage.
        matches = select(found, spec["source"], name)
        if len(matches) != 1 or identity(matches[0]) != spec["source"]:
            errors.append(
                f"{name}: approved JVM symbol is missing or ambiguous at this pin"
            )
            continue
        source = matches[0]
        try:
            derived = propose_value(
                source,
                since=spec["since"],
                families=families,
                defaults=evidence.get(
                    (source.owner, source.jvm_name, source.jvm_descriptor)
                ),
                role=spec.get("kind"),
            )
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            continue
        if _derived(derived) != _derived(spec):
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
