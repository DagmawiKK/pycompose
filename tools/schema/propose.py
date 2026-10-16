"""Propose value bindings from the pinned inventory; never edit the approved schema.

Run ``./gradlew dumpComposeDefaults`` in android/ first, then e.g.
``python tools/schema/propose.py Dp --out proposal.json``, or
``python tools/schema/propose.py --refresh`` to rebind the whole catalog.

Three shapes of public API are covered, each by one reusable policy:

* an ordinary constructor or factory (``propose_value``)
* the named members of a class -- every public property of a given type
  (``propose_members``), which is how theme roles and families are derived
* an extension property over a scalar (``propose_extension``)

Anything else is refused with a reason, never guessed.
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
    "value_families",
]

from schema.propose_families import (
    bind,
    propose_extension,
    propose_icons,
    propose_members,
    propose_value,
    propose_vocabulary,
)
from schema.propose_lookup import (
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
        if "family" in spec
    ]


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
