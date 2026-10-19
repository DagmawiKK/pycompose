"""Resolve every approved component entry to one pinned native overload.

The value side has recorded the compiler's own binding since the first tranche:
``source`` names the exact constructor, and drift checks compare against it.
Components were checked against the union of parameter names across every
overload of a name, and that union cannot tell two siblings apart: an entry
could claim a parameter from one overload and a parameter from another and
still pass.

This module derives the native argument face a generated adapter passes --
``component_face`` owns those rules -- and resolves it to exactly one pinned
declaration, or says why none can be selected. Three modes exist:

* ``derived`` -- the face selects one overload; the entry's recorded ``source``
  must equal it.
* ``anchored`` -- the call is hand-written (a resource wrapper passes a
  ``Painter`` the wire face never names); the entry must record the overload
  its call binds, and the pin must still declare that identity.
* ``manual`` -- the adapter is hand-written and legitimately spans a family of
  overloads; no single identity is claimed, and the union-membership check
  remains as the weaker boundary.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - only when run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.schema.classpath_dump import DUMP_DIR, Declaration, Inventory, inventory
from tools.schema.component_face import Face, accepts, face
from tools.schema.propose_lookup import ancestors


@dataclass(frozen=True)
class Resolution:
    """One entry's resolved binding, or the reason it has none.

    Attributes:
        name: The component's schema name.
        mode: ``derived``, ``anchored``, ``manual``, or ``refused``.
        source: The selected identity, when exactly one overload was selected.
        recorded: The identity the approved entry records, when present.
        face: The native argument face the resolution used.
        errors: Reasons the binding is not sound.
        differences: Facts a reviewer must apply, such as a missing source.
    """

    name: str
    mode: str
    source: dict[str, Any] | None
    recorded: dict[str, Any] | None
    face: Face
    errors: tuple[str, ...] = ()
    differences: tuple[str, ...] = ()


def identity(declaration: Declaration) -> dict[str, str]:
    """Read one declaration's exact pinned identity.

    Args:
        declaration: A pinned declaration.

    Returns:
        The artifact, owner, name, JVM name, and JVM descriptor.
    """
    return {
        "artifact": declaration.artifact,
        "owner": declaration.owner,
        "name": declaration.name,
        "jvmName": declaration.jvm_name or declaration.name,
        "descriptor": declaration.jvm_descriptor or "",
    }


def spell(source: dict[str, str]) -> str:
    """Spell one identity for a message.

    Args:
        source: An identity as :func:`identity` reads it.

    Returns:
        A single-line reference to the declaration.
    """
    return (
        f"{source.get('artifact', '?')} "
        f"{source.get('owner', '?')}.{source.get('jvmName', '?')}"
        f"{source.get('descriptor', '')}"
    )


def _candidates(
    name: str, entry: dict[str, Any], found: Inventory
) -> list[Declaration]:
    """Every pinned declaration of one approved component in its package."""
    return [
        declaration
        for declaration in found.declarations
        if declaration.name == name
        and declaration.package == entry.get("package")
        and declaration.disposition in {"ui", "support"}
        and declaration.parameters
    ]


def _manual(
    name: str, recorded: dict[str, str] | None, candidates: list[Declaration]
) -> Resolution:
    """Resolve a hand-written adapter that claims no single identity."""
    errors: tuple[str, ...] = ()
    if recorded is not None and not any(
        identity(declaration) == recorded for declaration in candidates
    ):
        errors = (f"{name}: recorded source is not pinned: {spell(recorded)}",)
    return Resolution(name, "manual", None, recorded, Face((), False, (), ()), errors)


def _derived(
    name: str,
    recorded: dict[str, str] | None,
    problems: tuple[str, ...],
    derived: Face,
    declaration: Declaration,
) -> Resolution:
    """Assemble the contract for the one overload the face selects."""
    source = identity(declaration)
    if recorded is None:
        return Resolution(
            name,
            "derived",
            source,
            recorded,
            derived,
            problems,
            (f"{name}: source is not recorded; review {spell(source)}",),
        )
    errors = problems
    if recorded != source:
        errors = (
            *errors,
            f"{name}: recorded source {spell(recorded)} differs from the "
            f"pinned overload {spell(source)}",
        )
    return Resolution(name, "derived", source, recorded, derived, errors)


def _refusal(
    entry: dict[str, Any],
    candidates: list[Declaration],
    accepted: list[Declaration],
) -> str:
    """Say why no single overload could be selected."""
    if entry.get("wrapper"):
        if not candidates:
            return f"no pinned overload in {entry.get('package')!r}"
        return (
            "wrapper call passes parameters the wire face never names; "
            "record the overload its call binds"
        )
    if not candidates:
        return f"no pinned overload in {entry.get('package')!r}"
    if not accepted:
        return "no pinned overload accepts the entry's arguments"
    identities = ", ".join(sorted(spell(identity(d)) for d in accepted))
    return (
        f"{len(accepted)} pinned overloads accept the entry's arguments "
        f"({identities}); none is selected"
    )


def resolve(
    name: str,
    entry: dict[str, Any],
    found: Inventory,
    registry: dict[str, Any],
    hierarchy: dict[str, set[str]],
) -> Resolution:
    """Resolve one approved entry to one pinned overload.

    Args:
        name: The component's schema name.
        entry: The approved component entry.
        found: The validated pinned inventory.
        registry: The approved component registry.
        hierarchy: Class ancestry over the pin, computed once by the caller.

    Returns:
        The resolution, with the errors that prevent a sound binding.
    """
    recorded = entry.get("source")
    candidates = _candidates(name, entry, found)
    if entry.get("adapter") == "manual":
        return _manual(name, recorded, candidates)
    pin_names = frozenset(
        parameter.name
        for declaration in candidates
        for parameter in declaration.parameters
    )
    derived = face(entry, registry, pin_names)
    problems = tuple(f"{name}.{problem}" for problem in derived.problems)
    accepted = [
        declaration
        for declaration in candidates
        if accepts(declaration, derived, entry, hierarchy)
    ]
    if len(accepted) == 1:
        return _derived(name, recorded, problems, derived, accepted[0])
    if recorded is not None:
        errors = problems
        if not any(identity(declaration) == recorded for declaration in candidates):
            errors = (
                *errors,
                f"{name}: recorded source is not pinned: {spell(recorded)}",
            )
        return Resolution(name, "anchored", None, recorded, derived, errors)
    reason = _refusal(entry, candidates, accepted)
    return Resolution(
        name, "refused", None, None, derived, (*problems, f"{name}: {reason}")
    )


def resolutions(registry: dict[str, Any], found: Inventory) -> list[Resolution]:
    """Resolve every approved component in catalog order.

    Args:
        registry: The approved component registry.
        found: The validated pinned inventory.

    Returns:
        One resolution per component, deterministic for a given pin.
    """
    hierarchy = ancestors(found)
    return [
        resolve(name, entry, found, registry, hierarchy)
        for name, entry in registry["components"].items()
    ]


def _contract(results: list[Resolution]) -> list[dict[str, Any]]:
    """Render resolutions as the JSON contract a reviewer reads."""
    return [
        {
            "name": result.name,
            "mode": result.mode,
            "source": result.source,
            "recorded": result.recorded,
            "arguments": [
                {
                    "name": argument.name,
                    "kind": argument.kind,
                    "classifier": argument.classifier,
                    "arity": argument.arity,
                    "receiver": argument.receiver,
                    "returns": argument.returns,
                }
                for argument in result.face.arguments
            ],
            "host": list(result.face.host),
            "problems": list(result.face.problems),
            "errors": list(result.errors),
            "differences": list(result.differences),
        }
        for result in results
    ]


def main(argv: list[str] | None = None) -> int:
    """Print the resolved contract for the approved catalog.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv``.

    Returns:
        A process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DUMP_DIR)
    parser.add_argument("--schema", type=Path, default=Path("schema/components.json"))
    parser.add_argument(
        "--summary", action="store_true", help="print one line per component"
    )
    parser.add_argument(
        "--sources",
        action="store_true",
        help="print the identities the catalog should record",
    )
    parser.add_argument("--out", type=Path, help="write the full contract as JSON")
    args = parser.parse_args(argv)
    try:
        registry = json.loads(args.schema.read_text())
        found = inventory(args.directory)
        results = resolutions(registry, found)
    except (OSError, ValueError) as exc:
        print(f"component_binding.py: {exc}", file=sys.stderr)
        return 2
    if args.sources:
        sources = {
            result.name: result.source
            for result in results
            if result.source is not None
        }
        print(json.dumps(sources, indent=2, sort_keys=True))
    if args.summary:
        for result in results:
            reference = spell(result.source) if result.source else "-"
            print(f"{result.name:28} {result.mode:9} {reference}")
            for message in result.errors:
                print(f"    error: {message}")
            for message in result.differences:
                print(f"    review: {message}")
    if args.out:
        args.out.write_text(
            json.dumps(_contract(results), indent=2, sort_keys=True) + "\n"
        )
    return int(any(result.errors for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
