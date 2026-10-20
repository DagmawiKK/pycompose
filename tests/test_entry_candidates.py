"""Candidates derive from plans and the pin; approval stays a human act.

The tool owns two guarantees worth pinning here: every wire fact (props,
defaults, slots, children, identity) is derived from one fresh call plan, and
nothing it does can approve itself -- staging is a deep-copied registry, stale
or ambiguous plans are refused, and the approved schema is only ever read.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from test_classpath_dump import (
    DUMP,
    ROOT,
    declaration,
    parameter,
    type_doc,
    write_inventory,
)

from tools.schema.candidate_props import CandidateError
from tools.schema.classpath_dump import Inventory, inventory
from tools.schema.component_binding import identity, spell
from tools.schema.entry_candidates import (
    check_fresh,
    derive,
    dumps,
    review_manifest,
    select,
    stage,
    verify,
)

PACKAGE = "androidx.compose.material3.test"
ARTIFACT = "androidx.compose.material3:material3-android:1.4.0"


def source(**changes: object) -> dict:
    """A plan's recorded identity with optional drift."""
    return {
        "artifact": ARTIFACT,
        "owner": f"{PACKAGE}.WidgetKt",
        "name": "Widget",
        "jvmName": "Widget",
        "descriptor": "(Landroidx/compose/ui/Modifier;)V",
    } | changes


def plan(parameters: dict, **changes: object) -> dict:
    """One call plan shaped like the planner's output."""
    return {
        "name": "Widget",
        "surface": "component",
        "status": "call-plan",
        "source": source(),
        "parameters": parameters,
        "gaps": [],
        "optIn": [],
        **changes,
    }


def family(
    name: str,
    kotlin_type: str,
    kind: str = "factory",
    values: tuple[str, ...] = (),
) -> dict:
    """One approved value family in the shape the catalog stores."""
    spec = {"family": name, "kotlinType": kotlin_type, "kind": kind}
    if values:
        spec["parameters"] = {
            "name": {"type": "string", "required": True, "values": list(values)}
        }
    return spec


def catalog(*families: dict) -> dict:
    """A catalog holding only the value families a test needs."""
    return {
        "schemaVersion": "1.0.0",
        "valueTypes": {spec["family"]: spec for spec in families},
        "components": {},
    }


def modifier() -> dict:
    """The one native parameter every generated call passes."""
    return {
        "policy": "modifier",
        "required": False,
        "type": {"nullable": False},
    }


def synthetic(tmp_path: Path, parameters: list[dict] | None = None) -> Inventory:
    """Load one synthetic pinned declaration a plan can record."""
    record = declaration(
        name="Widget",
        package=PACKAGE,
        owner=f"{PACKAGE}.WidgetKt",
        jvm={
            "name": "Widget",
            "descriptor": "(Landroidx/compose/ui/Modifier;)V",
            "matched": True,
        },
        parameters=parameters or [],
    )
    write_inventory(tmp_path, [record])
    return inventory(tmp_path)


def test_a_plan_derives_props_slots_children_and_defaults(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    registry = catalog(family("ChipColors", "androidx.compose.material3.ChipColors"))
    parameters = {
        "modifier": modifier(),
        "onClick": {
            "policy": "event",
            "payload": [],
            "required": True,
            "type": {"nullable": False},
        },
        "label": {
            "policy": "slot",
            "receiver": None,
            "required": True,
            "type": {"nullable": False},
        },
        "leadingIcon": {
            "policy": "slot",
            "receiver": None,
            "required": False,
            "type": {"nullable": True},
            "default": {"kind": "literal", "type": "kotlin/Nothing", "value": None},
        },
        "enabled": {
            "policy": "scalar",
            "wireType": "boolean",
            "required": False,
            "type": {"nullable": False},
            "default": {"kind": "literal", "type": "kotlin/Boolean", "value": True},
        },
        "colors": {
            "policy": "value",
            "family": "ChipColors",
            "required": False,
            "type": {"nullable": False},
            "default": {
                "kind": "call",
                "symbol": (
                    "androidx.compose.material3.AssistChipDefaults.assistChipColors"
                ),
            },
        },
        "content": {
            "policy": "slot",
            "receiver": "androidx/compose/foundation/layout/RowScope",
            "required": False,
            "type": {"nullable": True},
            "default": {"kind": "literal", "type": "kotlin/Nothing", "value": None},
        },
    }
    item = derive(
        plan(parameters, optIn=["androidx.compose.material3.ExperimentalMaterial3Api"]),
        found.declarations[0],
        registry,
        {"category": "test", "stability": "stable"},
    )
    entry = item.entry
    assert entry["package"] == PACKAGE
    assert entry["since"] == registry["schemaVersion"]
    assert entry["optIn"] == ["androidx.compose.material3.ExperimentalMaterial3Api"]
    assert entry["props"]["enabled"] == {"type": "boolean", "default": True}
    assert entry["props"]["onClick"] == {"type": "actionId", "required": True}
    assert entry["props"]["colors"] == {
        "type": "value",
        "valueType": "ChipColors",
        "nativeDefault": (
            "androidx.compose.material3.AssistChipDefaults.assistChipColors()"
        ),
    }
    assert list(entry["props"])[-1] == "modifier"
    assert entry["children"] == {
        "allowed": True,
        "kind": "content",
        "provides": "RowScope",
    }
    assert entry["slots"] == {
        "label": {"native": "label"},
        "leadingIcon": {"native": "leadingIcon", "nullable": True},
    }
    assert "content: app content children in RowScope" in item.review
    assert "label: required native slot; absence renders an empty lambda" in item.review


def test_a_decision_cannot_backdate_a_candidate(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    with pytest.raises(CandidateError, match="since"):
        derive(
            plan({"modifier": modifier()}),
            found.declarations[0],
            catalog(),
            {"category": "test", "stability": "stable", "since": "1.0.0"},
        )


def test_a_constant_family_derives_a_decoded_enum(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    registry = catalog(
        family(
            "Alignment",
            "androidx.compose.ui.Alignment",
            kind="constant",
            values=("TopStart", "BottomEnd"),
        )
    )
    parameters = {
        "modifier": modifier(),
        "contentAlignment": {
            "policy": "value",
            "family": "Alignment",
            "required": False,
            "type": {"nullable": False},
            "default": {
                "kind": "property",
                "symbol": "androidx.compose.ui.Alignment.TopStart",
            },
        },
    }
    item = derive(
        plan(parameters),
        found.declarations[0],
        registry,
        {"category": "test", "stability": "stable"},
    )
    assert item.entry["props"]["contentAlignment"] == {
        "type": "enum",
        "values": ["topStart", "bottomEnd"],
        "decode": "alignment",
        "default": "topStart",
    }


def test_unrenderable_defaults_omit_the_parameter_with_reasons(
    tmp_path: Path,
) -> None:
    found = synthetic(tmp_path)
    registry = catalog(family("ChipColors", "androidx.compose.material3.ChipColors"))
    parameters = {
        "modifier": modifier(),
        "colors": {
            "policy": "value",
            "family": "ChipColors",
            "required": False,
            "type": {"nullable": False},
            "default": {
                "kind": "call",
                "symbol": "androidx.compose.material3.Foo.colors",
                "arguments": [],
            },
        },
        "enabled": {
            "policy": "scalar",
            "wireType": "boolean",
            "required": False,
            "type": {"nullable": False},
            "default": {"kind": "property", "symbol": "androidx.compose.Foo.enabled"},
        },
        "count": {
            "policy": "scalar",
            "wireType": "int",
            "required": False,
            "type": {"nullable": True},
            "default": {"kind": "literal", "type": "kotlin/Nothing", "value": None},
        },
    }
    item = derive(
        plan(parameters),
        found.declarations[0],
        registry,
        {"category": "test", "stability": "stable"},
    )
    assert set(item.entry["props"]) == {"modifier"}
    assert any(
        "colors: omitted; default not renderable" in note for note in item.review
    )
    assert "enabled: omitted; the default is not a literal" in item.review
    assert any("count: omitted" in note for note in item.review)


def test_check_fresh_refuses_a_plan_from_another_pin(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    stale = {"formatVersion": 1, "bom": "2025.01.01", "compiler": found.compiler}
    with pytest.raises(CandidateError, match="bom"):
        check_fresh(stale, found)
    with pytest.raises(CandidateError, match="formatVersion"):
        check_fresh({"formatVersion": 2}, found)


def test_select_refuses_blocked_and_ambiguous_names(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    blocked = plan(
        {},
        status="blocked",
        gaps=[
            {
                "parameter": "content",
                "required": True,
                "reason": "slot-supplied arguments need typed context references",
            }
        ],
    )
    with pytest.raises(CandidateError, match="typed context references"):
        select({"candidates": [blocked]}, found, "Widget")
    first = plan({})
    second = plan({}, source=source(descriptor="(Lkotlin/jvm/functions/Function0;)V"))
    with pytest.raises(CandidateError, match="2 call plans"):
        select({"candidates": [first, second]}, found, "Widget")


def test_identity_selects_one_of_several_call_plans(tmp_path: Path) -> None:
    modifier_type = type_doc("androidx.compose.ui.Modifier")
    modifier_parameter = parameter("modifier", modifier_type, has_default=True)
    first = declaration(
        name="Widget",
        descriptor="(Landroidx/compose/ui/Modifier;)V",
        parameters=[modifier_parameter],
    )
    second = declaration(
        name="Widget",
        descriptor="(Landroidx/compose/ui/Modifier;Lkotlin/jvm/functions/Function0;)V",
        parameters=[modifier_parameter],
    )
    write_inventory(tmp_path, [first, second])
    found = inventory(tmp_path)
    plans = {
        "candidates": [
            plan(
                {"modifier": modifier()},
                source=identity(found.declarations[0]),
            ),
            plan(
                {"modifier": modifier()},
                source=identity(found.declarations[1]),
            ),
        ]
    }
    chosen = spell(identity(found.declarations[1]))
    selected, pin = select(plans, found, "Widget", identity=chosen)
    assert selected["source"] == identity(found.declarations[1])
    assert identity(pin) == identity(found.declarations[1])

    item = derive(
        selected,
        pin,
        catalog(),
        {"category": "test", "stability": "stable", "identity": chosen},
    )
    assert item.entry["source"] == identity(found.declarations[1])
    assert "identity" not in item.entry


def test_identity_must_match_exactly_one_call_plan(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    first = plan({})
    second = plan({}, source=source(descriptor="(Lkotlin/jvm/functions/Function0;)V"))
    plans = {"candidates": [first, second]}
    with pytest.raises(CandidateError, match="does not select one call plan"):
        select(plans, found, "Widget", identity="not-a-plan")
    with pytest.raises(CandidateError, match="does not disambiguate"):
        select(
            {"candidates": [first]}, found, "Widget", identity=spell(first["source"])
        )


def test_identity_must_be_a_non_empty_string(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    malformed: dict[str, Any] = {
        "category": "test",
        "stability": "stable",
        "identity": 3,
    }
    with pytest.raises(CandidateError, match="identity needs a non-empty string"):
        derive(plan({}), found.declarations[0], catalog(), malformed)


def test_an_int_scalar_carries_its_native_narrowing(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    parameters = {
        "modifier": modifier(),
        "count": {
            "policy": "scalar",
            "wireType": "int",
            "required": True,
            "type": {"classifier": "kotlin/Int", "nullable": False},
        },
    }
    item = derive(
        plan(parameters),
        found.declarations[0],
        catalog(),
        {"category": "test", "stability": "stable"},
    )
    assert item.entry["props"]["count"] == {
        "type": "integer",
        "nativeType": "Int",
        "minimum": -(2**31),
        "maximum": 2**31 - 1,
        "required": True,
    }


def test_a_dp_default_renders_as_member_access(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    parameters = {
        "modifier": modifier(),
        "elevation": {
            "policy": "value",
            "family": "Dp",
            "required": False,
            "type": {"classifier": "androidx/compose/ui/unit/Dp", "nullable": False},
            "default": {
                "kind": "extensionProperty",
                "symbol": "androidx.compose.ui.unit.dp",
                "receiver": {"kind": "literal", "type": "kotlin/Int", "value": 0},
            },
        },
    }
    item = derive(
        plan(parameters),
        found.declarations[0],
        catalog(family("Dp", "androidx.compose.ui.unit.Dp")),
        {"category": "test", "stability": "stable"},
    )
    assert item.entry["props"]["elevation"]["nativeDefault"] == "(0).dp"


def test_select_refuses_a_plan_the_pin_no_longer_declares(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    drifted = plan({}, source=source(descriptor="(DIFFERENT)V"))
    with pytest.raises(CandidateError, match="not pinned"):
        select({"candidates": [drifted]}, found, "Widget")
    ghost = plan(
        {"ghost": {"policy": "scalar", "wireType": "boolean", "required": False}}
    )
    with pytest.raises(CandidateError, match="disagree on parameters"):
        select({"candidates": [ghost]}, found, "Widget")


def test_stage_is_isolated_and_preserves_unrelated_policy(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    registry = {
        "schemaVersion": "1.0.0",
        "valueTypes": {"ChipColors": family("ChipColors", PACKAGE + ".ChipColors")},
        "components": {
            "Existing": {
                "package": PACKAGE,
                "category": "test",
                "stability": "stable",
                "props": {"modifier": {"type": "modifier"}},
                "children": {"allowed": False},
            }
        },
    }
    before = json.dumps(registry, sort_keys=True)
    item = derive(
        plan({"modifier": modifier()}),
        found.declarations[0],
        registry,
        {"category": "test", "stability": "stable"},
    )
    candidate = stage(registry, [item])
    assert json.dumps(registry, sort_keys=True) == before
    assert candidate["components"]["Existing"] == registry["components"]["Existing"]
    assert candidate["valueTypes"] == registry["valueTypes"]
    assert candidate["components"]["Widget"] == item.entry
    with pytest.raises(CandidateError, match="already approved"):
        stage(registry, [item, item])


def test_the_derivation_is_deterministic(tmp_path: Path) -> None:
    found = synthetic(tmp_path)
    registry = catalog(family("ChipColors", "androidx.compose.material3.ChipColors"))
    recorded = identity(found.declarations[0])
    first = derive(
        plan({"modifier": modifier()}, source=recorded),
        found.declarations[0],
        registry,
        {"category": "test", "stability": "stable"},
    )
    second = derive(
        plan({"modifier": modifier()}, source=recorded),
        found.declarations[0],
        registry,
        {"category": "test", "stability": "stable"},
    )
    assert dumps(first.entry) == dumps(second.entry)
    assert review_manifest({"bom": "b", "compiler": "c"}, [first]) == review_manifest(
        {"bom": "b", "compiler": "c"}, [second]
    )
    assert first.entry["source"] == recorded


def test_a_held_out_compatible_binding_derives_and_verifies() -> None:
    """A component the catalog does not carry still derives and verifies clean."""
    if os.environ.get("PYCOMPOSE_NATIVE_API_TESTS") != "1":
        pytest.skip("native CI runs the pinned artifact extraction")
    from tools.schema.classpath_dump import source_defaults
    from tools.schema.components import propose_components

    approved = json.loads((ROOT / "schema/components.json").read_text())
    found = inventory(DUMP)
    plans = propose_components(found, source_defaults(DUMP), approved)
    plan_record, pin = select(plans, found, "SmallFloatingActionButton")
    item = derive(
        plan_record,
        pin,
        approved,
        {"category": "test", "stability": "stable"},
    )
    assert verify(stage(approved, [item]), found, [item]) == []


def test_the_approved_pilot_entries_equal_their_derivation() -> None:
    if os.environ.get("PYCOMPOSE_NATIVE_API_TESTS") != "1":
        pytest.skip("native CI runs the pinned artifact extraction")
    from tools.schema.classpath_dump import source_defaults
    from tools.schema.components import propose_components

    approved = json.loads((ROOT / "schema/components.json").read_text())
    found = inventory(DUMP)
    plans = propose_components(found, source_defaults(DUMP), approved)
    review_input = {"category": "test", "stability": "stable"}
    for name in ("AssistChip", "ElevatedAssistChip", "Badge"):
        plan_record, pin = select(plans, found, name)
        entry = derive(plan_record, pin, approved, review_input).entry
        derived = {
            key: value
            for key, value in entry.items()
            if key not in {"category", "stability"}
        }
        expected = {
            key: value
            for key, value in approved["components"][name].items()
            if key not in {"category", "stability"}
        }
        assert derived == expected, name
