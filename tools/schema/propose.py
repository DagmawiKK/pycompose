"""Propose a ``components.json`` entry from AndroidX's published API.

    python tools/schema/propose.py Switch Card --artifact material3/material3
    python tools/schema/propose.py Switch --offline --out /tmp/switch.json

This **never writes ``schema/components.json``**. It prints a draft, because
three things in every entry are decisions the API dump cannot make:

* **Defaults.** The dump says ``optional boolean enabled`` and never what the
  default is. PyCompose's ``default`` is what *it* sends when the app omits the
  prop, which Compose knows nothing about.
* **Requiredness.** Most Material3 parameters are optional, and most should stay
  optional -- but "should" is a judgement.
* **Children.** Whether a component takes ordered children, named slots, or
  nothing at all is design, not API shape.

What the dump *does* give, and what this fills in automatically: the component's
name, its parameter list in order, which parameters cross as scalars, which are
callbacks carrying an actionId, which are content slots, and -- listed
explicitly -- every parameter that cannot cross and why.

The output is marked with ``TODO`` in every place a person has to decide, so a
review reads as a list of decisions rather than a wall of JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema.compose_api import (
    ARTIFACTS,
    Kind,
    Verdict,
    classify,
    composables,
    load,
)

MARKER = "TODO"
"""Left wherever a human has to decide something the dump cannot know."""


def suggest_name(upstream: str) -> str:
    """Return the schema name for a Compose function.

    Every component name matches Compose's exactly, so this is the identity. It
    stays as a function because the day that stops being true is the day this
    tool starts needing a decision table, and it should be visible when that is.

    Args:
        upstream: The name as Compose declares it.

    Returns:
        The name the schema uses.
    """
    return upstream


def propose(
    name: str,
    artifact: str,
    *,
    dump: str | None = None,
) -> dict[str, Any] | None:
    """Return a draft schema entry for one Compose function.

    Args:
        name: The name as Compose declares it.
        artifact: Which artifact to read it from.
        dump: Pre-loaded dump text, to avoid a fetch.

    Returns:
        The draft entry, or None when the artifact declares no such function.
    """
    text = dump if dump is not None else load(artifact)
    found = composables(text).get(name)
    if found is None:
        return None

    props: dict[str, Any] = {}
    dropped: list[str] = []
    slots: list[str] = []
    for parameter in found.parameters:
        verdict: Verdict = classify(parameter)
        if not verdict.crosses:
            dropped.append(f"{parameter.name}: {verdict.note or verdict.kind.value}")
            continue
        if verdict.kind is Kind.SLOT:
            slots.append(parameter.name)
            continue
        entry: dict[str, Any] = {"type": verdict.schema_type}
        if parameter.optional:
            entry[f"{MARKER}_default"] = MARKER
        else:
            entry["required"] = True
        props[suggest_name(parameter.name)] = entry

    entry = {
        "category": f"{MARKER}: buttons | controls | layout | surfaces | ...",
        "stability": f"{MARKER}: stable | experimental | beta",
        "props": props,
        "children": {"allowed": MARKER if slots else False},
    }
    if slots:
        entry[f"{MARKER}_slots"] = slots
    if dropped:
        entry[f"{MARKER}_dropped"] = dropped
    return entry


def render(name: str, entry: dict[str, Any]) -> str:
    """Return a draft entry as JSON, with the decisions called out.

    Args:
        name: The component name.
        entry: The draft entry.

    Returns:
        The JSON text to paste, plus a short list of what a person must decide.
    """
    body = json.dumps({name: entry}, indent=2)
    decisions = sorted(
        {
            line.strip().strip(",").strip('"')
            for line in body.splitlines()
            if MARKER in line
        }
    )
    todo = (
        "\nDecisions you have to make -- the dump cannot make them:\n"
        + "\n".join(f"  - {decision}" for decision in decisions)
        if decisions
        else "\nNothing to decide."
    )
    return f"{body}\n{todo}\n"


def main(argv: list[str] | None = None) -> int:
    """Run the proposer.

    Args:
        argv: Command-line arguments, defaulting to the process's.

    Returns:
        A process exit code: 1 when a name is not found.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="+", help="Compose function names")
    parser.add_argument(
        "--artifact",
        default="material3/material3",
        help=f"Which API dump to read; one of {', '.join(ARTIFACTS)}",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the cached dump and never reach the network",
    )
    parser.add_argument("--out", type=Path, help="Write drafts here instead of stdout")
    args = parser.parse_args(argv)

    try:
        dump = load(args.artifact, offline=args.offline)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2

    drafts: list[str] = []
    missing: list[str] = []
    for name in args.names:
        entry = propose(name, args.artifact, dump=dump)
        if entry is None:
            missing.append(name)
            continue
        drafts.append(render(suggest_name(name), entry))

    text = "\n".join(drafts)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    if missing:
        print(
            f"\nnot declared in {args.artifact}: {', '.join(missing)}", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
