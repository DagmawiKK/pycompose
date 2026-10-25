"""Propose value bindings from the pinned inventory; never edit the approved schema.

Run ``./gradlew dumpComposeDefaults`` in android/ first, then e.g.
``python tools/schema/propose.py Dp --out proposal.json``, or
``python tools/schema/propose.py --refresh`` to rebind the whole catalog.
``python tools/schema/propose.py --refresh --stage candidate.json`` writes the
approved catalog with the mechanical drift of a pin bump applied -- artifact
coordinates and additive vocabularies -- while every structural difference
stays in the approved schema and is listed for review. The candidate is never
the approved schema: approval remains a human act, review is a diff.

Three shapes of public API are covered, each by one reusable policy:

* an ordinary constructor or factory (``propose_value``)
* the named members of a class -- every public property of a given type
  (``propose_members``), which is how theme roles and families are derived
* an extension property over a scalar (``propose_extension``)

Anything else is refused with a reason, never guessed.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pycompose.compiler.classpath_dump import (
    DUMP_DIR,
    Inventory,
    inventory,
)

__all__ = [
    "EXTENSIONS",
    "ICONS",
    "MEMBERS",
    "SCALARS",
    "bind",
    "identity",
    "propose_icons",
    "propose_members",
    "propose_value",
    "propose_vocabulary",
    "propose_extension",
    "refresh",
    "source_name",
    "stage",
    "value_families",
]

from pycompose.compiler.propose_families import (
    bind,
    propose_extension,
    propose_members,
    propose_value,
    propose_vocabulary,
)
from pycompose.compiler.propose_icons import propose_icons
from pycompose.compiler.propose_lookup import (
    EXTENSIONS,
    ICONS,
    MEMBERS,
    SCALARS,
    identity,
    source_name,
    value_families,
)


def refresh(
    found: Inventory,
    evidence: dict[tuple[str, str, str], dict[str, Any]],
    registry: dict[str, Any],
) -> list[dict[str, Any]]:
    """Re-derive every approved binding without changing the approved schema.

    A family whose source is language-level (the range descriptor, ADR-0017
    decision 5) pins no artifact the compiler can resolve, so re-derivation
    skips it: its citation is approved policy, reviewed by a human, and the
    drift check stays silent rather than inventing a source.

    Args:
        found: The validated inventory of the current pin.
        evidence: Compiler-resolved defaults keyed by JVM identity.
        registry: The approved catalog.

    Returns:
        One result per binding: a proposal, explicit candidates, or a refusal.
    """
    return [
        bind(found, evidence, registry, name)
        for name, spec in registry["valueTypes"].items()
        if "family" in spec and "language" not in spec.get("source", {})
    ]


def _differences(
    approved: Any, proposal: Any, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], Any, Any]]:
    """Yield every leaf where a proposal differs from the approved binding."""
    if isinstance(approved, dict) and isinstance(proposal, dict):
        for key in sorted(set(approved) | set(proposal)):
            yield from _differences(
                approved.get(key), proposal.get(key), (*path, str(key))
            )
    elif approved != proposal:
        yield path, approved, proposal


def _adds_only(approved: Any, proposal: Any) -> bool:
    """Report whether a vocabulary value list only grew."""
    if not isinstance(approved, list) or not isinstance(proposal, list):
        return False
    try:
        return set(approved) <= set(proposal)
    except TypeError:  # pragma: no cover - unhashable vocabulary entries
        return False


def _markers(value: Any) -> bool:
    """Report whether a value is a marker list, an absent one included."""
    return value is None or (
        isinstance(value, list) and all(isinstance(item, str) for item in value)
    )


def _mechanical(path: tuple[str, ...], approved: Any, proposal: Any) -> bool:
    """Report whether one difference needs no new approval decision.

    A pin bump may rewrite an artifact coordinate, grow a vocabulary (a
    release adds a role or an icon and its holder) and change which markers a
    call needs: required opt-ins are derived from the pin's own annotations
    and signatures, so the tool restates them the way it restates
    coordinates. Identity, parameters, defaults and removals beyond those are
    approval decisions, and the staging step refuses to transcribe them.
    """
    if path == ("source", "artifact"):
        return isinstance(approved, str) and isinstance(proposal, str)
    if path == ("optIn",):
        return _markers(approved) and _markers(proposal)
    if len(path) == 3 and path[:2] == ("native", "owners"):
        return approved is None
    if len(path) == 3 and path[0] == "parameters" and path[2] == "values":
        return _adds_only(approved, proposal)
    return False


def stage(
    registry: dict[str, Any], proposals: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Apply a refresh's mechanical half to a copy of the approved catalog.

    Args:
        registry: The approved catalog, never mutated.
        proposals: The results of :func:`refresh`.

    Returns:
        The candidate registry, the names staged mechanically, and one note
        per binding that still needs a human decision.
    """
    candidate = copy.deepcopy(registry)
    staged: list[str] = []
    review: list[str] = []
    for result in proposals:
        name = result["name"]
        if "proposal" not in result:
            review.append(f"{name}: {result.get('unsupported', 'no proposal')}")
            continue
        differences = list(
            _differences(registry["valueTypes"][name], result["proposal"])
        )
        refused = [item for item in differences if not _mechanical(*item)]
        if refused:
            note = f"{name}: {'.'.join(refused[0][0])} differs"
            if len(refused) > 1:
                note += f" (+{len(refused) - 1} more)"
            review.append(note)
            continue
        for path, _, value in differences:
            field = candidate["valueTypes"][name]
            for step in path[:-1]:
                field = field[step]
            if value is None:
                # The proposal dropped the field where the pin no longer
                # requires it; a mechanical removal deletes, never nulls.
                del field[path[-1]]
            else:
                field[path[-1]] = value
        if differences:
            staged.append(name)
    return candidate, staged, review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rebind every approved value binding against the current pin.",
    )
    parser.add_argument("--directory", type=Path, default=DUMP_DIR)
    parser.add_argument("--schema", type=Path, default=Path("schema/catalog.lock.json"))
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--stage",
        type=Path,
        help="With --refresh, write a candidate registry holding mechanical drift.",
    )
    args = parser.parse_args(argv)
    try:
        from pycompose.compiler.classpath_dump import source_defaults

        found = inventory(args.directory)
        evidence = source_defaults(args.directory)
        registry = json.loads(args.schema.read_text())
        if args.stage and not args.refresh:
            raise ValueError("--stage applies a full --refresh")
        if args.stage and args.stage.resolve() == args.schema.resolve():
            raise ValueError("the staged candidate cannot be the approved schema")
        if args.refresh or not args.names:
            if args.names:
                raise ValueError("--refresh rebinds the whole catalog; drop the names")
            proposals = refresh(found, evidence, registry)
        else:
            proposals = [bind(found, evidence, registry, name) for name in args.names]
        if args.stage:
            candidate, staged, review = stage(registry, proposals)
            args.stage.write_text(json.dumps(candidate, indent=2) + "\n")
            for name in staged:
                print(f"staged: {name}")
            for note in review:
                print(f"needs review: {note}")
            print(f"{len(staged)} staged, {len(review)} need review")
        text = json.dumps(proposals, indent=2) + "\n"
        if args.out:
            if args.out.resolve() == args.schema.resolve():
                raise ValueError("proposals cannot overwrite the approved schema")
            args.out.write_text(text)
        elif not args.stage:
            print(text, end="")
    except (OSError, ValueError) as exc:
        print(f"propose.py: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
