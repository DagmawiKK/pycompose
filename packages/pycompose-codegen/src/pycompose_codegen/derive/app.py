"""Compile an app's own Compose libraries into its lock slice.

The library's lock covers Google's artifacts. An app that declares more
libraries extracts them the same way, into its own Android project, and the
same rules compile them: a component is exposed because it derives, refused
with the planner's reason otherwise. The app's policy may only add -- it names
components of the app's groups and never touches the library's. The result is
the app's lock slice, ``compose.lock.json``: its closure layer, so the evidence
can be re-extracted exactly, and its components, which codegen merges over the
library's catalog.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pycompose_codegen.derive.check import compare
from pycompose_codegen.derive.classpath_dump import inventory, source_defaults
from pycompose_codegen.derive.components import propose_components
from pycompose_codegen.derive.lock import Report, compile_components

APP_POLICY = "compose.policy.json"
"""The app's policy over its own libraries, beside ``pycompose.toml``; optional."""

ORIGIN = "app"
"""The ``origin`` a closure group carries when an app, not the library, declared it."""


class AppLibraryError(ValueError):
    """An app library cannot join the closure or compile."""


def layered_closure(
    default: dict[str, Any], resolved: dict[str, Any]
) -> dict[str, Any]:
    """The library's closure with the app's libraries layered on.

    Args:
        default: The library's ``compose-closure.json``.
        resolved: ``resolveComposeLibraries``' report: each library group's
            artifacts with their digests.

    Returns:
        A closure extracting the library's groups and the app's.

    Raises:
        AppLibraryError: If a library would move a module the BOM pins, or its
            group is one the library's closure already governs.
    """
    if resolved["conflicts"]:
        moved = ", ".join(
            f"{c['module']} {c['resolved']} (BOM {c['bom']})"
            for c in resolved["conflicts"]
        )
        raise AppLibraryError(f"needs Compose newer than the pinned BOM: {moved}")
    groups = dict(default["groups"])
    artifacts = list(default["artifacts"])
    for artifact in resolved["artifacts"]:
        group = artifact["coordinate"].split(":")[0]
        if group in groups and groups[group].get("origin") != ORIGIN:
            raise AppLibraryError(f"{group} is already in the library's closure")
        groups[group] = {
            "status": "extracted",
            "category": "app-surface",
            "domain": group,
            "components": True,
            "origin": ORIGIN,
        }
        artifacts.append({**artifact, "domain": group})
    return {**default, "groups": groups, "artifacts": artifacts}


def compile_app(
    directory: Path,
    android: Path,
    library: dict[str, Any],
    rules: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], Report]:
    """Compile the components of the app's own groups.

    Args:
        directory: Where the app's evidence was extracted.
        android: The app's Android project, holding its layered closure.
        library: The library's catalog lock.
        rules: The app's policy, per component.

    Returns:
        The app's lock slice, and the run's report.
    """
    found = inventory(directory, android)
    closure = json.loads((android / "compose-closure.json").read_text(encoding="utf-8"))
    own = {g for g, spec in closure["groups"].items() if spec.get("origin") == ORIGIN}
    sections = {k: v for k, v in library.items() if k not in {"components", "holders"}}
    plans = propose_components(found, source_defaults(directory, android), sections)
    plans = {
        **plans,
        "candidates": [
            plan
            for plan in plans["candidates"]
            if plan["source"]["artifact"].split(":")[0] in own
        ],
    }
    components, report = compile_components(
        rules, plans, found, sections, closure, frozenset(library["components"])
    )
    report.errors.extend(compare({**sections, "components": components}, found))
    lock = {
        "bom": found.bom,
        "closure": {
            "groups": {group: closure["groups"][group] for group in sorted(own)},
            "artifacts": [
                artifact
                for artifact in closure["artifacts"]
                if artifact["coordinate"].split(":")[0] in own
            ],
        },
        "components": dict(sorted(components.items())),
    }
    return lock, report
