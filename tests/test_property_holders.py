"""A holder with a factory and settable scalar properties needs no family code."""

from __future__ import annotations

import json
from pathlib import Path

from pycompose.codegen.adapters import render

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


def test_the_factory_seeds_what_the_setter_cannot() -> None:
    # The dial's hand is placed by rememberTimePickerState(initialHour) alone.
    properties = COMPONENTS["TimePicker"]["state"]["properties"]
    assert properties["hour"]["seed"] == {"parameter": "initialHour", "default": 0}
    assert properties["minute"]["seed"] == {"parameter": "initialMinute", "default": 0}
    # is24Hour defaults to the device's format, which no literal spells.
    assert "seed" not in properties["is24hour"]


def test_the_adapter_reconciles_each_property_through_the_factorys_holder() -> None:
    block = render("TimePicker", COMPONENTS["TimePicker"])
    assert "val stateHour = model.props.hour?.let { Wanted(it.toInt()) }" in block
    assert (
        "val stateValue = key(stateSeeds.generation) "
        "{ androidx.compose.material3.rememberTimePickerState("
        "initialHour = stateHour?.value ?: stateSeeds.previous?.hour ?: 0, "
        "initialMinute = stateMinute?.value ?: stateSeeds.previous?.minute ?: 0) }"
        in block
    )
    # A seeded property is driven by a new holder; the rest by the setter.
    assert (
        'context.reconcileProperty(stateValue, "hour", stateHour, '
        "model.props.onHourChange, { stateValue.hour }, "
        "{ stateSeeds.from(stateValue) }, seeded = true)" in block
    )
    assert "{ stateValue.is24hour = it })" in block
    assert "state = stateValue," in block
    date = render("DatePicker", COMPONENTS["DatePicker"])
    assert "model.props.selectedDateMillis.wanted { it.long }" in date
    assert "val stateValue = androidx.compose.material3.rememberDatePickerState()" in (
        date
    )
