"""Modifiers a composition scope declares: derivation, codegen and the API."""

from __future__ import annotations

import json

import pytest
from pycompose_codegen.derive.lock import LOCK
from pycompose_codegen.derive.scoped_modifiers import _named, modifier_props
from pycompose_codegen.emit.modifiers_kotlin import render_modifiers

from pycompose.errors import IrValidationError
from pycompose.ui import ExposedDropdownMenuAnchorType
from pycompose.ui.modifier import Modifier

MENU = "androidx.compose.material3.ExposedDropdownMenuBoxScope"


def _lock() -> dict:
    return json.loads(LOCK.read_text())


def test_the_menu_anchor_is_derived_from_its_scope_with_its_constant_family() -> None:
    lock = _lock()
    anchor = lock["modifiers"]["menuAnchor"]
    assert [s["scope"] for s in anchor["scoped"]] == [MENU]
    # "type" names the wire operation, so the parameter crosses renamed.
    assert "menuAnchorType" in anchor["props"]
    assert anchor["scoped"][0]["parameters"] == {"menuAnchorType": "type"}
    family = lock["valueTypes"]["ExposedDropdownMenuAnchorType"]
    assert family["parameters"]["name"]["values"] == [
        "PrimaryEditable",
        "PrimaryNotEditable",
        "SecondaryEditable",
    ]


def test_one_name_serves_every_scope_declaring_it_with_the_same_props() -> None:
    modifiers = _lock()["modifiers"]
    assert {s["scope"].rsplit(".", 1)[-1] for s in modifiers["weight"]["scoped"]} == {
        "ColumnScope",
        "RowScope",
    }
    # align takes a different alignment in each scope: one operation apiece.
    assert "align" not in modifiers
    assert {"boxAlign", "columnAlign", "rowAlign"} <= set(modifiers)


def test_props_that_differ_by_scope_are_named_after_their_scope() -> None:
    row = ({"scope": "a.RowScope", "native": "align"}, {"x": {"type": "string"}})
    box = ({"scope": "a.BoxScope", "native": "align"}, {"y": {"type": "string"}})
    refused: dict[str, str] = {}
    named = _named({"align": [row, box]}, frozenset({"boxAlign"}), refused)
    assert set(named) == {"rowAlign"}
    assert refused == {"boxAlign": "the name is ambiguous across scopes or with policy"}


def test_a_parameter_a_modifier_cannot_carry_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot take a slot"):
        modifier_props("a.Scope.m", {"content": {"policy": "slot"}}, {})


def test_the_host_call_binds_by_the_native_parameter_and_rejects_other_scopes() -> None:
    registry = {
        "modifiers": {
            "menuAnchor": {
                "props": {"menuAnchorType": {"type": "string", "required": True}},
                "scoped": [
                    {
                        "scope": MENU,
                        "native": "menuAnchor",
                        "parameters": {"menuAnchorType": "type"},
                    }
                ],
            }
        }
    }
    lines = [line.strip() for line in render_modifiers(registry).splitlines()]
    call = lines.index("Modifier.menuAnchor(")
    assert lines[call - 2 : call + 2] == [
        f"is {MENU} ->",
        "with(scope) {",
        "Modifier.menuAnchor(",
        'type = op.getValue("menuAnchorType").jsonPrimitive.content,',
    ]
    assert "else -> null" in lines


def test_scoped_operations_chain_like_the_hand_written_ones() -> None:
    anchor = ExposedDropdownMenuAnchorType("PrimaryNotEditable")
    assert Modifier.menu_anchor(anchor).to_wire() == {
        "operations": [
            {"type": "menuAnchor", "menuAnchorType": anchor, "enabled": True}
        ]
    }
    assert Modifier().padding(4).weight(2, fill=False).to_wire()["operations"] == [
        {"type": "padding", "value": 4},
        {"type": "weight", "weight": 2, "fill": False},
    ]


def test_an_alignment_outside_its_scope_vocabulary_is_rejected() -> None:
    with pytest.raises(IrValidationError):
        Modifier().row_align("centerHorizontally")  # type: ignore[arg-type]


def test_an_entry_keeps_the_version_it_entered_at() -> None:
    from pycompose_codegen.derive.lock import carried

    stamped = {"since": "1.24.0"}
    lock = {
        "components": {
            "Old": dict(stamped),
            "New": dict(stamped),
            "Text": dict(stamped),
        },
        "valueTypes": {},
    }
    carried(lock, {"components": {"Old": {"since": "1.22.0"}, "Text": {}}})
    # Re-stamped at a bump, 1.22 envelopes would stop accepting Old.
    assert lock["components"]["Old"] == {"since": "1.22.0"}
    assert lock["components"]["New"] == {"since": "1.24.0"}
    # The first schema's components carry none, and keep carrying none.
    assert lock["components"]["Text"] == {}
