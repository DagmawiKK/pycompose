"""Account for every declaration of the pinned target; approve nothing.

    python tools/schema/accounting.py --out android/build/compose-api/accounting.json
    python tools/schema/accounting.py --strict --summary

The denominator is every declaration the pinned extraction sees. Each one
carries the dump's own structural disposition, a capability domain resolved
from owners and receivers alone, and its approval and planning state. Reports
are deterministic, byte-stable and proposal-only: this tool never approves,
generates or edits the approved catalog.

What "accounted" means here:

* ``ui`` declarations are the app-facing composable denominator. Every overload
  is planned by :func:`tools.schema.components.propose_components` and lands in
  exactly one of ``call-plan`` or ``blocked`` (with a classified reason).
* ``support`` declarations are classified by what already consumes them: an
  approved value binding, a recognized holder (including nested owners such as
  icon objects), an approved composition scope, a planned call plan, or nothing
  yet. The unclaimed ones public UI can reach are reported grouped by owner --
  the support backlog -- never silently dropped.
* ``excluded`` declarations carry the dump's structural reason (non-public,
  restricted API, hidden compatibility declaration, synthetic/bridge method,
  annotation constructor) and are counted by reason, so no silent shrink is
  possible.
* ``error`` declarations are declaration-level extraction gaps; they and every
  diagnostic are listed in full.

Domains partition the surface into capability areas, derived from structure: a
``Modifier`` receiver is the modifiers domain wherever it is declared, and
otherwise the longest owner-package prefix decides. Anything unmapped is
reported as ``unclassified`` and fails ``--strict``. ``holders`` and
``tooling`` cover support the app surface never calls directly -- approved
holder objects and tooling-only declarations -- and say so.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - only when run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.schema.accounting_views import (
    approval_facts,
    empty_bucket,
    grounding,
    normalize,
    placement,
    protocols,
    receivers,
    recognition,
)
from tools.schema.classpath_dump import (
    DUMP_DIR,
    Inventory,
    inventory,
    source_defaults,
)
from tools.schema.components import MODIFIER, propose_components

DOMAIN_PREFIXES: tuple[tuple[str, str], ...] = (
    ("androidx.compose.material3.adaptive", "navigation"),
    ("androidx.compose.material3", "material"),
    ("androidx.compose.material", "material"),
    ("androidx.compose.foundation.text", "text"),
    ("androidx.compose.foundation", "foundation"),
    ("androidx.compose.ui.text", "text"),
    ("androidx.compose.ui.graphics", "graphics"),
    ("androidx.compose.ui.input", "input"),
    ("androidx.compose.ui.focus", "input"),
    ("androidx.compose.ui.semantics", "input"),
    ("androidx.compose.ui", "foundation"),
    ("androidx.compose.animation", "animation"),
    ("androidx.compose.runtime", "runtime"),
    ("androidx.navigationevent", "navigation"),
    ("androidx.navigation3", "navigation"),
    ("androidx.navigation", "navigation"),
    ("androidx.window", "navigation"),
    ("androidx.activity", "interop"),
    ("androidx.lifecycle", "interop"),
    ("androidx.paging", "interop"),
    ("androidx.constraintlayout", "interop"),
    ("androidx.inspection", "tooling"),
    ("androidx.savedstate", "interop"),
)
"""Longest-prefix capability domain per owner package. See the module docstring."""

DOMAINS: tuple[str, ...] = (
    "material",
    "foundation",
    "modifiers",
    "text",
    "graphics",
    "animation",
    "input",
    "runtime",
    "navigation",
    "interop",
    "holders",
    "tooling",
)
"""Every capability area of the target, present even when it has no declarations."""

GAP_CLASSES: tuple[tuple[str, str], ...] = (
    ("no wire policy for", "value-binding"),
    ("event payload needs a structured value codec", "payload-codec"),
    ("receiver/generic declaration needs a native protocol", "runtime-protocol"),
    ("slot scope needs a native protocol", "scope-protocol"),
    ("slot-supplied arguments need typed context references", "scope-protocol"),
    ("optional slot needs an explicit null policy", "slot-policy"),
    (
        "overload identity is not addressable by named arguments",
        "overload-discrimination",
    ),
    ("synchronous result needs a provider/predicate protocol", "provider-protocol"),
    ("missing compiler-resolved default", "defaults-evidence"),
    ("default: ", "defaults-evidence"),
    ("varargs need a collection binding", "collection-binding"),
    ("modifier default is not the native identity", "modifier-default"),
    ("opt-in marker is not accessible outside the pin", "exposure-fail-closed"),
)
"""Planner gap reason -> the class of work that would close it."""


def domain_of(owner: str, classifiers: Iterable[str]) -> str:
    """Resolve one declaration's capability domain from structure alone.

    Args:
        owner: The declaration's dotted owner.
        classifiers: Receiver classifiers of the declaration, slash form.

    Returns:
        A domain name from :data:`DOMAINS`, or ``unclassified``.
    """
    for classifier in classifiers:
        if classifier == MODIFIER:
            return "modifiers"
    for prefix, domain in DOMAIN_PREFIXES:
        if owner == prefix or owner.startswith(prefix + "."):
            return domain
    return "unclassified"


def gap_class(reason: str) -> str:
    """Classify one planner gap reason by the work that would close it.

    Args:
        reason: The planner's recorded reason.

    Returns:
        A class name, or ``unclassified`` for a reason the table does not know.
    """
    for prefix, name in GAP_CLASSES:
        if reason.startswith(prefix):
            return name
    return "unclassified"


def account(
    found: Inventory, defaults: dict[Any, Any], registry: dict[str, Any]
) -> dict[str, Any]:
    """Account for every declaration of one pinned inventory.

    Args:
        found: The pinned inventory.
        defaults: Compiler-resolved defaults for the pin.
        registry: The approved catalog.

    Returns:
        The deterministic account report.
    """
    plan = propose_components(found, defaults, registry)
    candidates = plan["candidates"]
    facts = approval_facts(registry, candidates)
    approved_calls = {
        spec["package"] + "." + name for name, spec in registry["components"].items()
    }
    required = found.required_support
    required_identities = {
        (declaration.owner, declaration.jvm_name, declaration.jvm_descriptor)
        for declaration in required
    }
    dispositions = Counter(d.disposition for d in found.declarations)
    excluded = Counter(
        d.reason or "unrecorded"
        for d in found.declarations
        if d.disposition == "excluded"
    )
    support_recognition: Counter[str] = Counter()
    unrecognized_owners: Counter[str] = Counter()
    domain_data: dict[str, dict[str, Any]] = {
        domain: empty_bucket() for domain in DOMAINS
    }
    for declaration in found.declarations:
        domain = domain_of(declaration.owner, receivers(declaration))
        bucket = domain_data.setdefault(domain, empty_bucket())
        bucket["declarations"][declaration.disposition] += 1
        if declaration.disposition != "support":
            continue
        state = recognition(declaration, facts)
        support_recognition[state] += 1
        bucket["support"][state] += 1
        identity = (
            declaration.owner,
            declaration.jvm_name,
            declaration.jvm_descriptor,
        )
        if state == "unrecognized" and identity in required_identities:
            unrecognized_owners[normalize(declaration.owner)] += 1
    for candidate in candidates:
        received = (
            [candidate["receiver"]["classifier"]] if candidate["receiver"] else []
        )
        domain = domain_of(normalize(candidate["source"]["owner"]), received)
        bucket = domain_data.setdefault(domain, empty_bucket())
        surface, state = placement(candidate, approved_calls)
        bucket[surface][state].add(candidate["name"])
        bucket["overloads"][state] += 1
        for gap in candidate["gaps"]:
            bucket["gaps"][gap_class(gap["reason"])] += 1
    domains: dict[str, Any] = {}
    for domain in sorted(domain_data):
        data = domain_data[domain]
        domains[domain] = {
            "declarations": dict(sorted(data["declarations"].items())),
            "components": {
                key: sorted(value) for key, value in data["components"].items()
            },
            "hooks": {key: sorted(value) for key, value in data["hooks"].items()},
            "support": dict(sorted(data["support"].items())),
            "gaps": dict(sorted(data["gaps"].items())),
            "overloads": dict(sorted(data["overloads"].items())),
        }
    gap_classes: Counter[str] = Counter()
    unclassified_reasons: Counter[str] = Counter()
    for candidate in candidates:
        for gap in candidate["gaps"]:
            name = gap_class(gap["reason"])
            gap_classes[name] += 1
            if name == "unclassified":
                unclassified_reasons[gap["reason"]] += 1
    errors = sorted(
        (
            {
                "artifact": declaration.artifact,
                "owner": declaration.owner,
                "name": declaration.name,
                "message": declaration.reason or "unrecorded",
            }
            for declaration in found.declarations
            if declaration.disposition == "error"
        ),
        key=lambda item: (item["owner"], item["name"], item["artifact"]),
    )
    diagnostics = [
        {"message": item.get("message", ""), "target": bool(item.get("target"))}
        for item in found.document.get("diagnostics", [])
    ]
    return {
        "formatVersion": 1,
        "pin": {
            "bom": found.bom,
            "compiler": found.compiler,
            "artifacts": sorted({d.artifact for d in found.declarations}),
        },
        "denominator": {
            "declarations": len(found.declarations),
            "dispositions": dict(sorted(dispositions.items())),
            "excludedReasons": dict(sorted(excluded.items())),
            "requiredSupport": len(required),
        },
        "domains": domains,
        "supportRecognition": dict(sorted(support_recognition.items())),
        "unrecognizedRequiredOwners": dict(sorted(unrecognized_owners.items())),
        "protocols": protocols(registry),
        "grounding": grounding(registry, plan, found),
        "gaps": {
            "classes": dict(sorted(gap_classes.items())),
            "unclassifiedReasons": dict(sorted(unclassified_reasons.items())),
            "extractionErrors": errors,
            "diagnostics": diagnostics,
        },
    }


def strict_findings(report: dict[str, Any]) -> list[str]:
    """List every condition ``--strict`` refuses.

    The bar is what must never hold: an incomplete partition, a planner reason
    outside the classification table, an approved value source no longer on
    the pin, or a target diagnostic. Approved components the planner does not
    plan stay a reported coverage delta rather than a refusal, because the
    extraction's UI classification is still narrower than the approved
    catalog; the report names them either way.

    Args:
        report: A report from :func:`account`.

    Returns:
        One message per finding; empty means the account is complete.
    """
    findings: list[str] = []
    if "unclassified" in report["domains"]:
        findings.append("domains: unclassified declarations present")
    if report["gaps"]["unclassifiedReasons"]:
        findings.append("gaps: unclassified planner reasons present")
    if report["grounding"]["ungroundedValues"]:
        findings.append("grounding: approved value sources are not on the pin")
    if [item for item in report["gaps"]["diagnostics"] if item["target"]]:
        findings.append("extraction: target diagnostics present")
    return findings


def summarize(report: dict[str, Any]) -> str:
    """Render a compact human summary of an account.

    Args:
        report: A report from :func:`account`.

    Returns:
        The summary text, one line per section.
    """
    totals: Counter[str] = Counter()
    for data in report["domains"].values():
        totals.update(data["overloads"])
    grounding_view = report["grounding"]
    lines = [
        f"pin: bom {report['pin']['bom']} compiler {report['pin']['compiler']}",
        "denominator: "
        + ", ".join(
            f"{name} {count}"
            for name, count in report["denominator"]["dispositions"].items()
        ),
        "plan: "
        + ", ".join(
            f"{name} {totals[name]}" for name in ("approved", "planned", "blocked")
        ),
        "support: "
        + ", ".join(
            f"{name} {count}" for name, count in report["supportRecognition"].items()
        ),
        f"grounding: unplanned approved components"
        f" {len(grounding_view['ungroundedComponents'])},"
        f" ungrounded value sources {len(grounding_view['ungroundedValues'])}",
        "gaps: "
        + ", ".join(
            f"{name} {count}" for name, count in report["gaps"]["classes"].items()
        ),
    ]
    for domain in sorted(report["domains"]):
        data = report["domains"][domain]
        overloads = data["overloads"]
        lines.append(
            f"  {domain}: ui {data['declarations'].get('ui', 0)}"
            f" support {data['declarations'].get('support', 0)}"
            f" | approved {overloads.get('approved', 0)}"
            f" planned {overloads.get('planned', 0)}"
            f" blocked {overloads.get('blocked', 0)}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Write the account report, never a registry or generated artifact.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv[1:]``.

    Returns:
        Zero on success, two on refusal.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DUMP_DIR)
    parser.add_argument("--schema", type=Path, default=Path("schema/catalog.lock.json"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    protected = {
        args.schema.resolve(),
        (root / "schema/catalog.lock.json").resolve(),
        (root / "pycompose/schema/catalog.lock.json").resolve(),
    }
    if args.out and args.out.resolve() in protected:
        parser.error("an account cannot overwrite an approved schema")
    try:
        report = account(
            inventory(args.inventory),
            source_defaults(args.inventory),
            json.loads(args.schema.read_text()),
        )
        text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            args.out.write_text(text)
        elif not args.summary:
            print(text, end="")
        if args.summary:
            print(summarize(report))
        if args.strict:
            findings = strict_findings(report)
            for finding in findings:
                print(f"accounting: {finding}", file=sys.stderr)
            if findings:
                return 2
    except (OSError, ValueError) as exc:
        print(f"accounting.py: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
