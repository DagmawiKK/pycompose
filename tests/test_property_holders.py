"""A holder with a factory and settable scalar properties needs no family code."""

from __future__ import annotations

import json
from pathlib import Path

from pycompose.schema.codegen.adapters import render

LOCK = json.loads(
    (Path(__file__).resolve().parents[1] / "schema/catalog.lock.json").read_text()
)
COMPONENTS = LOCK["components"]


def test_each_settable_property_is_stated_and_reported() -> None:
    picker = COMPONENTS["TimePicker"]
    assert picker["state"]["kind"] == "properties"
    assert (
        picker["state"]["factory"]
        == "androidx.compose.material3.rememberTimePickerState"
    )
    assert picker["props"]["hour"] == {"type": "integer"}
    assert picker["props"]["onHourChange"]["payload"] == [
        {"name": "hour", "type": "integer"}
    ]
    # A nullable property clears to null: absent states nothing.
    date = COMPONENTS["DatePicker"]["props"]
    assert date["selectedDateMillis"] == {"type": "integer", "nullable": True}


def test_a_holder_with_a_read_only_property_is_not_derived() -> None:
    # DateRangePickerState only reads its selection: setting it needs a drive.
    assert "DateRangePicker" not in COMPONENTS


def test_the_adapter_reconciles_each_property_through_the_factorys_holder() -> None:
    block = render("TimePicker", COMPONENTS["TimePicker"])
    assert (
        "val stateValue = androidx.compose.material3.rememberTimePickerState()" in block
    )
    assert (
        'context.reconcileProperty(stateValue, "hour", '
        "model.props.hour?.let { Wanted(it.toInt()) }" in block
    )
    assert "state = stateValue," in block
    date = render("DatePicker", COMPONENTS["DatePicker"])
    assert "model.props.selectedDateMillis.wanted { it.long }" in date
