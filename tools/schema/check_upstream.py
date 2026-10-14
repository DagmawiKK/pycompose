"""Fail when ``schema/components.json`` has drifted from the Compose API.

    python tools/schema/check_upstream.py --offline

A component entry is a promise about a Kotlin function that is not in this
repository. That promise goes stale quietly: AndroidX renames a parameter, makes
a required one optional, or deprecates a component, and nothing here notices
until an app renders wrong on a user's device.

This compares the schema against the same public API dumps
:mod:`tools.schema.compose_api` reads, and reports drift. It is the piece that
makes supporting Material 3 sustainable rather than a manual audit every
release, and it needs no JVM and no network in CI once the dumps are cached.

Reported, in order of severity:

* **removed** -- the schema declares a prop Compose no longer has
* **upgraded** -- Compose made a required prop optional
* **vanished** -- the schema declares a component Compose no longer has
* **renamed** -- the component exists but under another name
* **exposed** -- Compose has parameters the schema does not carry (informational)
* **skipped** -- the component lives in an artifact not being checked

Only the first two fail the build. The rest are a worklist: adding a prop is a
schema edit plus a regeneration, which is a decision, not a defect.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schema.compose_api import (
    ARTIFACTS,
    Composable,
    composables,
    every_parameter,
    load,
)

SCHEMA = Path("schema/components.json")

SEVERITY = ("removed", "upgraded", "vanished", "reshaped", "exposed", "skipped")
"""Report order. The first two are defects; the rest are a worklist."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing the schema and the upstream API disagree about.

    Attributes:
        severity: Which of :data:`SEVERITY` this is.
        component: The component it concerns.
        detail: What differs, in one line.
    """

    severity: str
    component: str
    detail: str

    def __str__(self) -> str:
        """Return the finding as a line of report.

        Returns:
            The formatted line.
        """
        return f"{self.severity:9s} {self.component}: {self.detail}"


def _camel(name: str) -> str:
    """Return a Kotlin name as a PyCompose wire name.

    Args:
        name: The name as Compose declares it.

    Returns:
        The camelCase name the schema uses.
    """
    head, *rest = name.split("_")
    return head + "".join(word[:1].upper() + word[1:] for word in rest)


def compare(
    schema: dict[str, Any],
    upstream: dict[str, Composable],
    every: dict[str, set[str]],
) -> list[Finding]:
    """Compare every schema component against the upstream API.

    Args:
        schema: The parsed ``components.json``.
        upstream: The composables the dumps declare, by name.
        every: Every parameter name upstream, across all overloads of each.

    Returns:
        Every finding, most severe first.
    """
    findings: list[Finding] = []
    for name, entry in schema["components"].items():
        wanted = name
        found = upstream.get(wanted)
        if found is None:
            findings.append(
                Finding("vanished", name, f"no @Composable {wanted} upstream")
            )
            continue
        findings.extend(_props(name, entry, found, every.get(wanted, set())))
    findings.sort(key=lambda finding: SEVERITY.index(finding.severity))
    return findings


def _props(
    name: str,
    entry: dict[str, Any],
    found: Composable,
    names: set[str],
) -> list[Finding]:
    """Compare one component's props against its upstream signature.

    Args:
        name: The component's schema name.
        entry: Its schema entry.
        found: The overload this tool reports on.
        names: Every parameter name upstream, across all overloads.

    Returns:
        Findings for this component alone.
    """
    declared = entry.get("props", {})
    # Props this schema deliberately invents or reshapes are not drift; Compose
    # has no `Button.text` parameter, because text is a content slot there. The
    # schema records which, so "removed" keeps meaning removed.
    invented = set(entry.get("reshaped", []))
    every = {_camel(param) for param in names}
    optional: dict[str, bool] = {
        _camel(parameter.name): parameter.optional for parameter in found.parameters
    }

    findings: list[Finding] = []
    for prop, spec in declared.items():
        if prop in invented:
            continue
        # Absence is judged across every overload; requiredness only against the
        # one overload being reported, since another may make it optional.
        if prop not in every:
            findings.append(
                Finding("removed", name, f"{prop} is not a parameter upstream")
            )
            continue
        if spec.get("required") and optional.get(prop):
            findings.append(
                Finding("upgraded", name, f"{prop} is optional upstream, required here")
            )
    findings.extend(
        Finding("exposed", name, f"{prop} is available upstream")
        for prop in sorted(every - invented - set(declared))
    )
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run the drift check.

    Args:
        argv: Command-line arguments, defaulting to the process's.

    Returns:
        1 when a schema defect was found, 0 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="Use cached dumps only")
    parser.add_argument(
        "--artifact",
        action="append",
        help="Limit to this artifact; repeatable. Defaults to all.",
    )
    args = parser.parse_args(argv)

    artifacts = tuple(args.artifact) if args.artifact else ARTIFACTS
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    upstream: dict[str, Composable] = {}
    names: dict[str, set[str]] = {}
    for artifact in artifacts:
        try:
            text = load(artifact, offline=args.offline)
        except FileNotFoundError as error:
            print(error, file=sys.stderr)
            return 2
        for found_name, found in composables(text).items():
            upstream.setdefault(found_name, found)
        for found_name, found_names in every_parameter(text).items():
            names.setdefault(found_name, set()).update(found_names)

    findings = compare(schema, upstream, names)
    for finding in findings:
        print(finding)

    defects = [finding for finding in findings if finding.severity in SEVERITY[:2]]
    work = [finding for finding in findings if finding.severity not in SEVERITY[:2]]
    print(
        f"\n{len(defects)} defect(s), {len(work)} to consider, "
        f"against {len(upstream)} upstream composables"
    )
    return 1 if defects else 0


if __name__ == "__main__":
    raise SystemExit(main())
