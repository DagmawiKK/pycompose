"""Proposal generator flow: native calls, CLI, batches and refusals."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_classpath_dump import DUMP, declaration, parameter, type_doc, write_inventory
from test_component_proposals import (
    assert_calls_resolve_to_recorded_identities,
)


def test_generated_native_calls_render_defaults_slots_and_events(
    native_document, tmp_path
):
    from dataclasses import replace

    from pycompose.schema.codegen.native_calls import call_name, render_call
    from tools.schema.classpath_dump import Declaration, inventory, source_defaults
    from tools.schema.components import propose_components

    assert native_document["provenance"]["bom"] == "2026.09.00"
    schema = Path("schema/catalog.lock.json")
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
        "gradle.projectsEvaluated { gradle.rootProject.project(':renderer').android."
        f"sourceSets.test.kotlin.srcDir({json.dumps(str(tmp_path))}) }}"
    )
    result = subprocess.run(
        [
            "./gradlew",
            "-Pkotlin.incremental=false",
            "--init-script",
            str(init),
            ":renderer:testDebugUnitTest",
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
        Path(
            "android/renderer/build/intermediates/built_in_kotlinc/debugUnitTest/"
            "compileDebugUnitTestKotlin/classes/com/pycompose/proof"
        ),
    )


def test_cli_refuses_to_overwrite_the_approved_schema(tmp_path):
    import sys

    schema = Path("schema/catalog.lock.json")
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
    from tools.schema.classpath_dump import inventory
    from tools.schema.components import propose_components

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.components import propose_components

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.components import propose_components

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.components import propose_components

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.components import propose_components

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.components import propose_components

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.components import propose_components

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
    from tools.schema.classpath_dump import inventory
    from tools.schema.components import propose_components

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
