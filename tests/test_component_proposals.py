"""The batch proposal boundary never approves or collapses native APIs."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from test_classpath_dump import DUMP


def source_prefix(descriptor: str) -> str:
    """The declared arguments, without the Composer and its synthetic masks."""
    return descriptor.split("Landroidx/compose/runtime/Composer;")[0]


def assert_calls_resolve_to_recorded_identities(report, classes: Path) -> None:
    """Prove every facade compiles into a call to the overload it recorded.

    Compiling a forwarding call is not proof of overload identity: leaving an
    optional argument out can let Kotlin bind a same-named sibling. The
    compiler's own choice is readable from the bytecode, so it is compared
    against the recorded JVM name and declared arguments rather than inferred.
    """
    assert classes.is_dir(), f"no compiled facades in {classes}"
    targets = set()
    for path in sorted(classes.glob("*.class")):
        dumped = subprocess.run(
            ["javap", "-p", "-c", str(path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for name, descriptor in re.findall(r"// Method (\S+):(\S+)", dumped):
            if name.startswith("androidx/compose/"):
                # javap quotes JVM names carrying `-`, as Compose's mangled
                # composable names do.
                targets.add((name.replace('"', ""), descriptor))
    unresolved = []
    for plan in report["candidates"]:
        if plan["status"] != "call-plan":
            continue
        owner = (
            f"{plan['source']['owner'].replace('.', '/')}.{plan['source']['jvmName']}"
        )
        wanted = source_prefix(plan["source"]["descriptor"])
        if not any(
            name == owner and source_prefix(descriptor) == wanted
            for name, descriptor in targets
        ):
            unresolved.append(f"{plan['name']} {plan['source']['jvmName']}")
    assert not unresolved, unresolved


def test_pinned_ui_defaults_cover_every_exact_overload(native_document):
    from tools.schema.classpath_dump import inventory, source_defaults

    assert native_document["provenance"]["compiler"] == "2.4.21"
    found = inventory(DUMP)
    defaults = source_defaults(DUMP)
    assert len(found.ui) == 187
    assert all((s.owner, s.jvm_name, s.jvm_descriptor) in defaults for s in found.ui)


def test_pinned_unconstructible_types_and_enum_vocabularies(native_document) -> None:
    from tools.schema.classpath_dump import inventory, source_defaults
    from tools.schema.propose import bind

    assert native_document["provenance"]["bom"] == "2026.09.00"
    found = inventory(DUMP)
    evidence = source_defaults(DUMP)
    schema = json.loads(Path("schema/components.json").read_text())
    empty = {"schemaVersion": "1.12.0", "valueTypes": {}}
    # Painter is an abstract class: its bytecode constructor proves nothing an
    # app can call, so it can never become a value family.
    assert bind(found, evidence, empty, "Painter")["unsupported"] == (
        "class cannot be constructed"
    )
    tristate = bind(found, evidence, schema, "ToggleableState")["proposal"]
    assert tristate["parameters"]["name"]["values"] == ["Indeterminate", "Off", "On"]


def test_pinned_denominator_separates_components_from_styling_hooks(native_document):
    from tools.schema.classpath_dump import inventory, source_defaults
    from tools.schema.components import propose_components

    assert native_document["provenance"]["bom"] == "2026.09.00"
    report = propose_components(
        inventory(DUMP),
        source_defaults(DUMP),
        json.loads(Path("schema/components.json").read_text()),
    )
    component_coverage = report["coverage"]["components"]
    hook_coverage = report["coverage"]["hooks"]
    # Pin-derived denominators describe the committed dump (bom 2026.09.00) and
    # move only when the pinned evidence moves, never with catalog policy.
    assert component_coverage["names"] == 118
    assert component_coverage["overloads"] == 159
    assert hook_coverage["names"] == 20
    assert hook_coverage["overloads"] == 28
    # The callPlan/blocked split follows the protocols the catalog has activated,
    # so it must stay a decomposition rather than a memorized count.
    assert (
        component_coverage["callPlan"] + component_coverage["blocked"]
        == component_coverage["overloads"]
    )
    assert hook_coverage["callPlan"] == 0
    assert hook_coverage["blocked"] == hook_coverage["overloads"]
    hooks = {c["name"] for c in report["candidates"] if c["surface"] == "hook"}
    assert {"Thumb", "Container", "Indicator", "InputField"} <= hooks
    # The approved value families closed their own gaps, and nothing else.
    reasons = {entry["reason"] for entry in report["worklist"]}
    assert not [r for r in reasons if "BorderStroke" in r or "ToggleableState" in r]
    # A member of a provided scope is app-composed, not a hook.
    assert "ExposedDropdownMenu" not in hooks
    assert (
        next(c for c in report["candidates"] if c["name"] == "ExposedDropdownMenu")[
            "surface"
        ]
        == "component"
    )


def test_the_shipped_catalog_carries_no_unexplained_prop(native_document) -> None:
    """A prop the host fills must say so, or the drift check reads it as removed.

    The component drift check is what keeps a parameter vanishing under a new
    release from passing as an approved binding, and it exempts exactly what the
    catalog calls ``reshaped``. A prop with no pinned counterpart but a *host*
    filler -- an observed interaction, a state's desired value or its report --
    has to be listed there too; otherwise the gate stays red for a reason the
    schema alone does not show.
    """
    from tools.schema.check_upstream import compare
    from tools.schema.classpath_dump import inventory

    assert native_document["provenance"]["compiler"] == "2.4.21"
    registry = json.loads(Path("schema/components.json").read_text())
    assert compare(registry, inventory(DUMP)) == []


def test_the_drift_check_re_derives_a_package_and_a_provider(native_document) -> None:
    """Both facts the generator reads are facts of the pin, not of the catalog.

    The package decides which composable a generated adapter imports, and a
    provider's return type decides whether the wire value can be handed over at
    all, so a stale one has to fail here rather than become a coercion nobody
    checked.
    """
    from tools.schema.check_upstream import compare
    from tools.schema.classpath_dump import inventory

    assert native_document["provenance"]["compiler"] == "2.4.21"
    found = inventory(DUMP)

    def edited(**changes) -> dict:
        registry = json.loads(Path("schema/components.json").read_text())
        entry = registry["components"]["LinearProgressIndicator"]
        for key, value in changes.items():
            provider = entry["props"]["progress"]["provider"]
            if key == "package":
                entry["package"] = value
            else:
                provider[key] = value
        return registry

    assert compare(edited(package="androidx.compose.example"), found) == [
        "LinearProgressIndicator: package 'androidx.compose.example' is not "
        "pinned (androidx.compose.material, androidx.compose.material3)"
    ]
    assert compare(edited(returns="Long"), found) == [
        "LinearProgressIndicator.progress: provider returns 'Long' is not "
        "pinned (Float)"
    ]
    assert compare(edited(native="state"), found) == [
        "LinearProgressIndicator.progress: provider parameter 'state' is not "
        "a pinned zero-arg function"
    ]


def test_the_drift_check_re_derives_receivers_and_provided_scopes(
    native_document,
) -> None:
    """A scope fact is a fact of the pin, on both sides of the relationship.

    A component the pin prefixes with a scope cannot be looked up like a plain
    one, and a parent's content lambda carries a receiver exactly when the pin
    says it does. Both are re-derived, so dropping either -- or promising a
    scope the pin never hands down -- fails here rather than becoming a call
    that cannot compile.
    """
    from tools.schema.check_upstream import compare
    from tools.schema.classpath_dump import inventory

    assert native_document["provenance"]["compiler"] == "2.4.21"
    found = inventory(DUMP)

    def edited(name: str, **changes) -> dict:
        registry = json.loads(Path("schema/components.json").read_text())
        entry = registry["components"][name]
        for key, value in changes.items():
            if key == "provides":
                entry["children"][key] = value
            else:
                entry[key] = value
        return registry

    # ``NavigationBarItem`` is declared ``RowScope.NavigationBarItem``: every
    # overload carries the receiver, so silence about it is drift.
    assert compare(edited("NavigationBarItem", scope=None), found) == [
        "NavigationBarItem: every pinned overload is a scope extension; "
        "declare 'scope'"
    ]
    assert compare(edited("NavigationBarItem", scope="ColumnScope"), found) == [
        "NavigationBarItem: scope 'ColumnScope' is not a pinned declaration's receiver"
    ]
    assert compare(edited("NavigationBar", provides="ColumnScope"), found) == [
        "NavigationBar: children.provides 'ColumnScope' is not the pinned "
        "content lambda's receiver"
    ]
    assert compare(edited("Row", provides=None), found) == [
        "Row: pinned content composes under RowScope; declare children.provides"
    ]
