"""The batch proposal boundary never approves or collapses native APIs."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from test_classpath_dump import DUMP, declaration, parameter, type_doc, write_inventory


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
    from schema.classpath_dump import inventory, source_defaults

    assert native_document["provenance"]["compiler"] == "2.0.21"
    found = inventory(DUMP)
    defaults = source_defaults(DUMP)
    assert len(found.ui) == 155
    assert all((s.owner, s.jvm_name, s.jvm_descriptor) in defaults for s in found.ui)


def test_pinned_unconstructible_types_and_enum_vocabularies(native_document) -> None:
    from schema.classpath_dump import inventory, source_defaults
    from schema.propose import bind

    assert native_document["provenance"]["bom"] == "2025.01.01"
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
    from schema.classpath_dump import inventory, source_defaults
    from schema.components import propose_components

    assert native_document["provenance"]["bom"] == "2025.01.01"
    report = propose_components(
        inventory(DUMP),
        source_defaults(DUMP),
        json.loads(Path("schema/components.json").read_text()),
    )
    component_coverage = report["coverage"]["components"]
    hook_coverage = report["coverage"]["hooks"]
    # Pin-derived denominators describe the committed dump (bom 2025.01.01) and
    # move only when the pinned evidence moves, never with catalog policy.
    assert component_coverage["names"] == 99
    assert component_coverage["overloads"] == 132
    assert hook_coverage["names"] == 17
    assert hook_coverage["overloads"] == 23
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


def test_generated_native_calls_render_defaults_slots_and_events(
    native_document, tmp_path
):
    from dataclasses import replace

    from pycompose.schema.codegen.native_calls import call_name, render_call
    from schema.classpath_dump import Declaration, inventory, source_defaults
    from schema.components import propose_components

    assert native_document["provenance"]["bom"] == "2025.01.01"
    schema = Path("schema/components.json")
    original = schema.read_bytes()
    report = propose_components(
        inventory(DUMP), source_defaults(DUMP), json.loads(original)
    )
    selected = {}
    for name in ("Text", "Switch", "Button", "AlertDialog"):
        plans = [
            p
            for p in report["candidates"]
            if p["name"] == name and p["status"] == "call-plan"
        ]
        if name == "Text":
            plans = [p for p in plans if p["parameters"]["text"]["policy"] == "scalar"]
        if name == "AlertDialog":
            plans = [p for p in plans if "confirmButton" in p["parameters"]]
        assert len(plans) == 1, plans
        plan = plans[0]
        selected[name] = call_name(plan)
    for plan in report["candidates"]:
        if plan["status"] == "call-plan":
            (tmp_path / f"{call_name(plan)}.kt").write_text(
                render_call(plan, package="com.pycompose.proof")
            )
    source = Path("tests/fixtures/native_calls/GeneratedCallsProof.kt").read_text()
    for name, function in selected.items():
        source = source.replace(f"CALL_{name}", function)
    unit = type_doc("kotlin/Unit")
    probe = declaration(
        "PolicyProbe",
        "probe",
        package="com.pycompose.proof",
        owner="com.pycompose.proof.ProbeKt",
        parameters=[
            parameter("first", type_doc("kotlin/Int"), True),
            parameter("second", type_doc("kotlin/Boolean"), True),
            parameter("ratio", type_doc("kotlin/Float"), True),
            parameter(
                "onReport",
                type_doc(
                    "kotlin/Function2",
                    type_doc("kotlin/Int"),
                    type_doc("kotlin/String") | {"nullable": True},
                    unit,
                ),
            ),
            parameter(
                "onCancel",
                type_doc("kotlin/Function0", unit) | {"nullable": True},
                True,
            ),
            parameter(
                "content",
                type_doc(
                    "kotlin/Function0",
                    unit,
                    annotations=("androidx/compose/runtime/Composable",),
                ),
            ),
        ],
    )
    evidence = {
        ("com.pycompose.proof.ProbeKt", "PolicyProbe", "probe"): {
            "first": {"kind": "literal", "type": "kotlin/Int", "value": 3},
            "second": {"kind": "literal", "type": "kotlin/Boolean", "value": True},
            "ratio": {"kind": "literal", "type": "kotlin/Float", "value": 1.5},
            "onCancel": {"kind": "literal", "type": "kotlin/Nothing", "value": None},
        }
    }
    probe_inventory = replace(inventory(DUMP), declarations=(Declaration.read(probe),))
    probe_plan = propose_components(probe_inventory, evidence, {})["candidates"][0]
    (tmp_path / "ProbeCall.kt").write_text(
        render_call(probe_plan, package="com.pycompose.proof")
    )
    source = source.replace("CALL_Probe", call_name(probe_plan))
    (tmp_path / "GeneratedCallsProof.kt").write_text(source)
    init = tmp_path / "proof.gradle"
    init.write_text(
        "gradle.projectsEvaluated { gradle.rootProject.project(':host').android."
        f"sourceSets.test.java.srcDir({json.dumps(str(tmp_path))}) }}"
    )
    result = subprocess.run(
        [
            "./gradlew",
            "-Pkotlin.incremental=false",
            "--init-script",
            str(init),
            ":host:testDebugUnitTest",
            "--tests",
            "com.pycompose.proof.GeneratedCallsProof",
            "--console=plain",
        ],
        cwd="android",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert schema.read_bytes() == original
    assert_calls_resolve_to_recorded_identities(
        report,
        Path("android/host/build/tmp/kotlin-classes/debugUnitTest/com/pycompose/proof"),
    )


def test_cli_refuses_to_overwrite_the_approved_schema(tmp_path):
    import sys

    schema = Path("schema/components.json")
    original = schema.read_bytes()
    linked = tmp_path / "linked.json"
    linked.symlink_to(schema.resolve())
    result = subprocess.run(
        [sys.executable, "tools/schema/components.py", "--out", str(linked)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "cannot overwrite an approved schema" in result.stderr
    assert schema.read_bytes() == original


def test_batch_preserves_overloads_and_reports_required_and_optional_gaps(tmp_path):
    from schema.classpath_dump import inventory
    from schema.components import propose_components

    records = [
        declaration(
            "Sample",
            "string",
            parameters=[parameter("value", type_doc("kotlin/String"))],
        ),
        declaration(
            "Sample",
            "state",
            parameters=[parameter("state", type_doc("example/State"))],
        ),
        declaration(
            "Other",
            "optional",
            parameters=[parameter("state", type_doc("example/State"), True)],
        ),
    ]
    write_inventory(tmp_path, records)
    approved = {"components": {}, "valueTypes": {}}
    before = json.dumps(approved)
    report = propose_components(inventory(tmp_path), {}, approved)
    assert report["status"] == "proposal-only"
    components = report["coverage"]["components"]
    assert components["names"] == 2
    assert components["overloads"] == 3
    assert components["callPlan"] == 2
    assert components["blocked"] == 1
    assert report["coverage"]["hooks"]["overloads"] == 0
    assert report["coverage"]["enabled"] == 0
    assert report["coverage"]["compiled"] == 0
    samples = [p for p in report["candidates"] if p["name"] == "Sample"]
    assert len(samples) == 2
    blocked = next(p for p in samples if p["source"]["descriptor"] == "state")
    assert blocked["status"] == "blocked"
    assert blocked["gaps"][0]["parameter"] == "state"
    assert blocked["gaps"][0]["required"] is True
    other = next(p for p in report["candidates"] if p["name"] == "Other")
    assert other["status"] == "call-plan"
    assert other["parameters"]["state"]["policy"] == "omit"
    assert other["gaps"][0]["required"] is False
    assert report["worklist"] == [
        {
            "reason": "no wire policy for example/State",
            "blocks": ["Sample"],
            "hooks": [],
            "limits": ["Other"],
        }
    ]
    assert json.dumps(approved) == before
    write_inventory(tmp_path, list(reversed(records)))
    assert propose_components(inventory(tmp_path), {}, approved) == report


def test_styling_hooks_leave_the_component_denominator(tmp_path):
    from schema.classpath_dump import inventory
    from schema.components import propose_components

    row_scope = type_doc("androidx/compose/foundation/layout/RowScope")
    missing = type_doc("example/Missing")
    records = [
        # A scope-bound component: the app composes it inside the row provider.
        declaration(
            "Inside",
            "scoped",
            owner="androidx.compose.foundation.layout.RowScope",
            dispatchReceiver=row_scope,
            parameters=[parameter("value", missing)],
        ),
        # A styling hook: reachable only as a parameter of the component above.
        declaration(
            "Thumb",
            "hook",
            owner="example.SliderDefaults",
            dispatchReceiver=type_doc("example/SliderDefaults"),
            parameters=[parameter("value", missing)],
        ),
        # The provider that makes RowScope a scope an app receives.
        declaration(
            "Row",
            "provider",
            parameters=[
                parameter(
                    "content",
                    type_doc(
                        "kotlin/Function1",
                        row_scope,
                        type_doc("kotlin/Unit"),
                        annotations=(
                            "androidx/compose/runtime/Composable",
                            "kotlin/ExtensionFunctionType",
                        ),
                    ),
                )
            ],
        ),
    ]
    write_inventory(tmp_path, records)
    report = propose_components(
        inventory(tmp_path), {}, {"components": {}, "valueTypes": {}}
    )

    surfaces = {p["name"]: p["surface"] for p in report["candidates"]}
    assert surfaces == {"Inside": "component", "Thumb": "hook", "Row": "component"}
    assert report["coverage"]["components"] == {
        "names": 2,
        "overloads": 2,
        "callPlan": 1,
        "blocked": 1,
    }
    assert report["coverage"]["hooks"] == {
        "names": 1,
        "overloads": 1,
        "callPlan": 0,
        "blocked": 1,
    }
    # Hook gaps never read as component blockers, and a hook still records the
    # capability its owner would need.
    assert report["worklist"] == [
        {
            "reason": "no wire policy for example/Missing",
            "blocks": ["Inside"],
            "hooks": ["Thumb"],
            "limits": [],
        },
        {
            "reason": "receiver/generic declaration needs a native protocol",
            "blocks": ["Inside"],
            "hooks": ["Thumb"],
            "limits": [],
        },
    ]


def test_parameter_policies_use_types_not_component_or_parameter_names(tmp_path):
    from schema.classpath_dump import inventory
    from schema.components import propose_components

    unit = type_doc("kotlin/Unit")
    record = declaration(
        "NeverListedBefore",
        parameters=[
            parameter("active", type_doc("kotlin/Boolean"), True),
            parameter("decoration", type_doc("androidx/compose/ui/Modifier"), True),
            parameter("shade", type_doc("androidx/compose/ui/graphics/Color"), True),
            parameter(
                "changed",
                type_doc(
                    "kotlin/Function2",
                    type_doc("kotlin/Int"),
                    type_doc("kotlin/String"),
                    unit,
                ),
            ),
            parameter(
                "body",
                type_doc(
                    "kotlin/Function1",
                    type_doc("androidx/compose/foundation/layout/RowScope"),
                    unit,
                    annotations=(
                        "androidx/compose/runtime/Composable",
                        "kotlin/ExtensionFunctionType",
                    ),
                ),
            ),
        ],
    )
    write_inventory(tmp_path, [record])
    registry = {
        "valueTypes": {
            "Color": {
                "family": "Color",
                "kotlinType": "androidx.compose.ui.graphics.Color",
            }
        }
    }
    evidence = {
        ("androidx.compose.material3.TextKt", "NeverListedBefore", "signature"): {
            "active": {"kind": "literal", "type": "kotlin/Boolean", "value": True},
            "shade": {
                "kind": "property",
                "symbol": "androidx.compose.ui.graphics.Color.Unspecified",
            },
            "decoration": {
                "kind": "object",
                "symbol": "androidx.compose.ui.Modifier.Companion",
            },
        }
    }
    candidate = propose_components(inventory(tmp_path), evidence, registry)[
        "candidates"
    ][0]
    assert candidate["status"] == "call-plan"
    assert candidate["call"] == "androidx.compose.material3.NeverListedBefore"
    assert {k: v["policy"] for k, v in candidate["parameters"].items()} == {
        "active": "scalar",
        "decoration": "modifier",
        "shade": "value",
        "changed": "event",
        "body": "slot",
    }
    assert candidate["parameters"]["changed"]["payload"] == [
        {"name": "arg0", "type": "int", "nullable": False},
        {"name": "arg1", "type": "string", "nullable": False},
    ]
    assert (
        candidate["parameters"]["body"]["receiver"]
        == "androidx/compose/foundation/layout/RowScope"
    )
    assert candidate["dependencies"] == {
        "values": ["Color"],
        "scopes": ["androidx/compose/foundation/layout/RowScope"],
    }
    assert candidate["approval"] == "required"
    assert candidate["verification"] == {
        "compiled": False,
        "rendered": False,
        "stateControlled": False,
    }


def test_unsafe_defaults_and_behavior_are_never_exposed_as_ignored_props(tmp_path):
    from schema.classpath_dump import inventory
    from schema.components import propose_components

    record = declaration(
        parameters=[
            parameter("first", type_doc("kotlin/Float"), True),
            parameter("second", type_doc("kotlin/Float"), True),
            parameter(
                "predicate",
                type_doc(
                    "kotlin/Function1",
                    type_doc("kotlin/Int"),
                    type_doc("kotlin/Boolean"),
                ),
            ),
        ]
    )
    write_inventory(tmp_path, [record])
    evidence = {
        ("androidx.compose.material3.TextKt", "Text", "signature"): {
            "first": {"kind": "unsupported", "reason": "dependent parameter default"},
            "second": {
                "kind": "call",
                "symbol": "probe.factory",
                "arguments": ["first"],
            },
        }
    }
    candidate = propose_components(inventory(tmp_path), evidence, {})["candidates"][0]
    assert candidate["status"] == "blocked"
    assert [p["policy"] for p in candidate["parameters"].values()] == [
        "omit",
        "omit",
        "blocked",
    ]
    assert len(candidate["gaps"]) == 3
    assert "dependent parameter default" in candidate["gaps"][0]["reason"]
    assert "default" in candidate["gaps"][1]["reason"]


def test_overloads_distinguished_by_a_required_parameter_stay_addressable(tmp_path):
    from pycompose.schema.codegen.native_calls import render_call
    from schema.classpath_dump import inventory
    from schema.components import propose_components

    unit = type_doc("kotlin/Unit")
    records = [
        declaration(
            "Card",
            "plain",
            parameters=[parameter("content", type_doc("kotlin/Function0", unit))],
        ),
        declaration(
            "Card",
            "clickable",
            parameters=[
                parameter("onClick", type_doc("kotlin/Function0", unit)),
                parameter("content", type_doc("kotlin/Function0", unit)),
            ],
        ),
    ]
    write_inventory(tmp_path, records)
    report = propose_components(inventory(tmp_path), {}, {})
    assert {p["status"] for p in report["candidates"]} == {"call-plan"}
    plain = next(
        p for p in report["candidates"] if p["source"]["descriptor"] == "plain"
    )
    # The sibling requires onClick, so a call without it cannot bind the
    # clickable overload and the plain one keeps its recorded identity.
    assert "`onClick`" not in render_call(plain, package="proof")


def test_overloads_a_call_cannot_tell_apart_are_refused(tmp_path):
    from schema.classpath_dump import inventory
    from schema.components import propose_components

    unit = type_doc("kotlin/Unit")
    records = [
        declaration(
            "Progress",
            "plain",
            parameters=[
                parameter("modifier", type_doc("androidx/compose/ui/Modifier"), True)
            ],
        ),
        declaration(
            "Progress",
            "detailed",
            parameters=[
                parameter("modifier", type_doc("androidx/compose/ui/Modifier"), True),
                parameter(
                    "track", type_doc("kotlin/Function3", unit, unit, unit, unit), True
                ),
            ],
        ),
    ]
    write_inventory(tmp_path, records)
    report = propose_components(inventory(tmp_path), {}, {})
    # `track` has no wire policy, so both overloads accept the same arguments
    # and neither can be selected by name.
    assert {p["status"] for p in report["candidates"]} == {"blocked"}
    assert all(
        any(g["reason"].startswith("overload identity") for g in p["gaps"])
        for p in report["candidates"]
    )


def test_optional_slot_without_null_policy_is_refused(tmp_path):
    from pycompose.schema.codegen.native_calls import render_call
    from schema.classpath_dump import inventory
    from schema.components import propose_components

    unit = type_doc("kotlin/Unit")
    record = declaration(
        "Sheet",
        "sheet",
        parameters=[
            parameter(
                "trailing",
                type_doc(
                    "kotlin/Function0",
                    unit,
                    annotations=("androidx/compose/runtime/Composable",),
                ),
                True,
            ),
        ],
    )
    write_inventory(tmp_path, [record])
    # A slot whose default the compiler could not resolve stays out of the call
    # and is recorded, so the omission is reviewable rather than defaulted by
    # guesswork.
    plan = propose_components(inventory(tmp_path), {}, {})["candidates"][0]
    assert plan["parameters"]["trailing"]["policy"] == "omit"
    assert plan["gaps"][0]["reason"] == "missing compiler-resolved default"
    assert "`trailing`" not in render_call(plan, package="proof")

    # The emitter refuses the same shape when a plan claims the slot is
    # forwarded without a null default to fall back to.
    plan["parameters"]["trailing"]["policy"] = "slot"
    plan["parameters"]["trailing"]["receiver"] = None
    plan["parameters"]["trailing"]["required"] = False
    with pytest.raises(ValueError, match="explicit null policy"):
        render_call(plan, package="proof")


def test_call_generation_refuses_blockers_and_opaque_expressions(tmp_path):
    import pytest

    from pycompose.schema.codegen.native_calls import render_call
    from schema.classpath_dump import inventory
    from schema.components import propose_components

    write_inventory(
        tmp_path,
        [declaration(parameters=[parameter("state", type_doc("example/State"))])],
    )
    plan = propose_components(inventory(tmp_path), {}, {})["candidates"][0]
    with pytest.raises(ValueError, match="blocked"):
        render_call(plan, package="proof")
    plan["status"] = "call-plan"
    with pytest.raises(ValueError, match="blocked"):
        render_call(plan, package="proof")


def test_the_shipped_catalog_carries_no_unexplained_prop(native_document) -> None:
    """A prop the host fills must say so, or the drift check reads it as removed.

    The component drift check is what keeps a parameter vanishing under a new
    release from passing as an approved binding, and it exempts exactly what the
    catalog calls ``reshaped``. A prop with no pinned counterpart but a *host*
    filler -- an observed interaction, a state's desired value or its report --
    has to be listed there too; otherwise the gate stays red for a reason the
    schema alone does not show.
    """
    from schema.check_upstream import compare
    from schema.classpath_dump import inventory

    assert native_document["provenance"]["compiler"] == "2.0.21"
    registry = json.loads(Path("schema/components.json").read_text())
    assert compare(registry, inventory(DUMP)) == []


def test_the_drift_check_re_derives_a_package_and_a_provider(native_document) -> None:
    """Both facts the generator reads are facts of the pin, not of the catalog.

    The package decides which composable a generated adapter imports, and a
    provider's return type decides whether the wire value can be handed over at
    all, so a stale one has to fail here rather than become a coercion nobody
    checked.
    """
    from schema.check_upstream import compare
    from schema.classpath_dump import inventory

    assert native_document["provenance"]["compiler"] == "2.0.21"
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
        "pinned (androidx.compose.material3)"
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
    from schema.check_upstream import compare
    from schema.classpath_dump import inventory

    assert native_document["provenance"]["compiler"] == "2.0.21"
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
