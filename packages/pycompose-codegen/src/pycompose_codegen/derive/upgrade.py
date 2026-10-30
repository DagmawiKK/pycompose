"""Move the library to a new Compose BOM in one command.

    python -m pycompose_codegen.derive upgrade --bom 2026.10.00

The pin changes, and everything that follows from it is regenerated rather
than edited: the closure's exact artifacts and digests, the evidence, the lock,
the signature file. Every lock change is then classified (``diff``): additive,
fidelity and metadata changes are accepted, behaviour and breaking ones need an
approval in ``schema/policy/approvals.json``. A component whose adapter is
written by hand, or which is held whole, is flagged whenever its entry changed,
since its Kotlin was written against the old declaration.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pycompose_codegen.checkout import ROOT
from pycompose_codegen.derive import signatures
from pycompose_codegen.derive.classpath_dump import ANDROID, DUMP_DIR, inventory
from pycompose_codegen.derive.diff import Change, classify, load_approvals, unapproved
from pycompose_codegen.derive.gradle import extract, resolve
from pycompose_codegen.derive.lock import LOCK, Report, dumps, generate
from pycompose_codegen.derive.policy import load

SIGNATURES = ROOT / "schema/signatures"
PIN = ANDROID / "gradle/libs.versions.toml"
_BOM = re.compile(r'^compose-bom = "([^"]+)"$', re.MULTILINE)


class UpgradeError(ValueError):
    """The upgrade cannot proceed: a moved module, or a compiler refusal."""


def refresh_closure(
    closure: dict[str, Any], resolved: dict[str, Any]
) -> dict[str, Any]:
    """The closure re-pinned to what the new BOM resolves.

    Group policy, domains and support reasons are decisions and stay; the
    artifacts, their versions and digests are evidence and are replaced.

    Args:
        closure: The closure as committed.
        resolved: ``resolveCompose``'s report for the new pin.

    Returns:
        The refreshed closure.

    Raises:
        UpgradeError: If something moved a module the new BOM pins.
    """
    if resolved["conflicts"]:
        moved = ", ".join(c["module"] for c in resolved["conflicts"])
        raise UpgradeError(f"modules moved off the new BOM: {moved}")

    def module(coordinate: str) -> str:
        return coordinate.rsplit(":", 1)[0]

    tooling = {module(entry["coordinate"]) for entry in closure["tooling"]}
    support = {module(entry["coordinate"]): entry for entry in closure["support"]}
    domains = {
        module(entry["coordinate"]): entry["domain"] for entry in closure["artifacts"]
    }
    artifacts, kept = [], []
    for found in resolved["artifacts"]:
        name = module(found["coordinate"])
        if name in tooling:
            continue
        if name in support:
            kept.append({**found, "reason": support[name]["reason"]})
            continue
        group = name.split(":")[0]
        domain = domains.get(name, closure["groups"][group]["domain"])
        artifacts.append({**found, "domain": domain})
    return {
        **closure,
        "artifacts": artifacts,
        "tooling": [{**entry, "domain": "tooling"} for entry in resolved["tooling"]],
        "support": kept,
    }


def dumps_closure(closure: dict[str, Any]) -> str:
    """Serialize a closure as it is committed: one entry per line, reviewable.

    Args:
        closure: The closure.

    Returns:
        Its text.
    """
    sections = []
    for key, value in closure.items():
        if isinstance(value, dict):
            body = ",\n".join(
                f"    {json.dumps(k)}: {json.dumps(v)}" for k, v in value.items()
            )
            sections.append(f"  {json.dumps(key)}: {{\n{body}\n  }}")
        elif isinstance(value, list):
            body = ",\n".join(f"    {json.dumps(entry)}" for entry in value)
            sections.append(f"  {json.dumps(key)}: [\n{body}\n  ]")
        else:
            sections.append(f"  {json.dumps(key)}: {json.dumps(value)}")
    return "{\n" + ",\n".join(sections) + "\n}\n"


def manual(lock: dict[str, Any], held: set[str]) -> set[str]:
    """Components whose Kotlin a person wrote: hand-written adapters and holds.

    Args:
        lock: A catalog lock.
        held: The components policy holds whole.

    Returns:
        Their names.
    """
    return held | {
        name
        for name, entry in lock["components"].items()
        if entry.get("adapter") == "manual" or entry.get("wrapper")
    }


def upgrade(version: str) -> tuple[list[Change], list[str], Report]:
    """Re-pin, re-extract and recompile; classify what changed.

    Args:
        version: The new Compose BOM.

    Returns:
        The classified changes, the hand-written components to review, and
        the compiler's report.

    Raises:
        UpgradeError: If the compiler refuses the new pin.
    """
    text = PIN.read_text(encoding="utf-8")
    current = _BOM.search(text)
    if current is None:
        raise UpgradeError(f"{PIN} names no compose-bom")
    closure_path = ANDROID / "compose-closure.json"
    closure_text = closure_path.read_text(encoding="utf-8")
    old = json.loads(LOCK.read_text(encoding="utf-8"))
    PIN.write_text(_BOM.sub(f'compose-bom = "{version}"', text), encoding="utf-8")
    compiled = False
    try:
        closure_path.write_text(
            dumps_closure(refresh_closure(json.loads(closure_text), resolve(ANDROID))),
            encoding="utf-8",
        )
        extract(ANDROID)
        policy = load()
        lock, report = generate(policy)
        if report.errors:
            raise UpgradeError("; ".join(report.errors))
        compiled = True
    finally:
        if not compiled:
            # A failed upgrade leaves the pin it found: nothing committed changed.
            PIN.write_text(text, encoding="utf-8")
            closure_path.write_text(closure_text, encoding="utf-8")
    LOCK.write_text(dumps(lock), encoding="utf-8")
    found = inventory(DUMP_DIR)
    for stale in SIGNATURES.glob("*.txt"):
        stale.unlink()
    (SIGNATURES / f"{found.bom}.txt").write_text(
        signatures.render(found), encoding="utf-8"
    )
    changes = classify(old, lock)
    held = {name for name, rule in policy.components.items() if "manual" in rule}
    written = manual(old, held) | manual(lock, held)
    review = sorted(
        name
        for name in written
        if any(change.id.startswith(f"components.{name}") for change in changes)
    )
    return changes, review, report


def main(version: str) -> int:
    """Run the upgrade and say what needs a person.

    Args:
        version: The new Compose BOM.

    Returns:
        0 when every change is accepted or approved, 1 otherwise.
    """
    changes, review, report = upgrade(version)
    for change in changes:
        print(f"{change.kind:10} {change.id}")
    for name in review:
        print(f"review     {name}: its Kotlin is written by hand and its entry changed")
    missing, stale = unapproved(changes, load_approvals())
    for change in missing:
        print(f"approve    {change.id} ({change.kind})")
    for approval in stale:
        print(f"stale      approval names no current change: {approval}")
    print(
        f"upgrade: {len(changes)} changes, {len(missing)} need approval, "
        f"{len(review)} hand-written to review; {len(report.promoted)} promoted. "
        f"Run tools/template/sync.py to carry the pin into the template."
    )
    return 1 if missing or stale else 0
