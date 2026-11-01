"""Each modifier policy declares names the native call the pin resolves it to."""

from __future__ import annotations

import json
from pathlib import Path

LOCK = Path(__file__).resolve().parents[4] / "schema" / "catalog.lock.json"
MODIFIERS = json.loads(LOCK.read_text())["modifiers"]
POLICY = json.loads((LOCK.parent / "policy" / "catalog.json").read_text())["modifiers"]


def test_every_policy_modifier_names_its_call() -> None:
    for name in POLICY:
        call = MODIFIERS[name]["call"]
        assert call["function"].endswith(f".{name}"), name
        assert set(call["arguments"]) == set(POLICY[name]["props"]), name


def test_a_prop_named_otherwise_binds_by_type_and_a_bare_dp_has_its_overload() -> None:
    call = MODIFIERS["padding"]["call"]
    assert call["arguments"]["value"]["parameter"] == "paddingValues"
    assert call["bare"]["value"]["parameter"] == "all"


def test_of_overloads_that_bind_the_one_with_fewest_defaults_in_use_is_called() -> None:
    # clickable(interactionSource = …) also takes enabled and onClick, but
    # leaves one more default in use; Kotlin calls the other, and so do we.
    source = MODIFIERS["clickable"]["call"]["source"]
    assert "MutableInteractionSource" not in source["descriptor"]


def test_a_block_taking_call_sets_its_receivers_members() -> None:
    call = MODIFIERS["semantics"]["call"]
    assert call["block"] == {
        "parameter": "properties",
        "receiver": "androidx.compose.ui.semantics.SemanticsPropertyReceiver",
    }
    arguments = call["arguments"]
    assert arguments["heading"]["member"] == "function"
    assert arguments["contentDescription"]["member"] == "property"
    assert arguments["role"]["constants"]["radioButton"] == "RadioButton"


def test_a_graphics_block_is_read_while_drawing() -> None:
    # graphicsLayer's block is a graphics scope, so Compose invokes it per
    # frame while it draws: a bound prop redraws and never recomposes.
    call = MODIFIERS["graphicsLayer"]["call"]
    assert call["phase"] == "draw"
    assert call["block"] == {
        "parameter": "block",
        "receiver": "androidx.compose.ui.graphics.GraphicsLayerScope",
    }
    assert call["arguments"]["alpha"]["member"] == "property"


def test_a_block_that_answers_with_a_value_is_read_while_laying_out() -> None:
    # offset's lambda returns IntOffset, which the pin's own IntOffset(x, y)
    # builds from the props; the dp reaches its Int parameter through Density.
    call = MODIFIERS["offset"]["call"]
    assert call["phase"] == "layout"
    result = call["block"]["result"]
    assert result["function"] == "androidx.compose.ui.unit.IntOffset"
    assert result["arguments"]["x"] == {
        "parameter": "x",
        "type": "kotlin.Int",
        "convert": "roundToPx",
    }


def test_a_block_on_a_scope_that_does_not_draw_reads_in_composition() -> None:
    # semantics' receiver is not a Density: Compose invokes it when it collects
    # what the node means, so a bound prop there is read where the composition
    # is and recomposes, exactly as a prop passed in the call does.
    call = MODIFIERS["semantics"]["call"]
    assert call["phase"] == "composition"
    assert MODIFIERS["semantics"]["props"]["traversalIndex"]["phase"] == "composition"


def test_every_bound_prop_states_the_phase_its_call_reads_it_in() -> None:
    for name, modifier in MODIFIERS.items():
        call = modifier.get("call")
        if call is None:
            continue
        for prop, spec in modifier["props"].items():
            if "animation" in spec:
                assert spec["phase"] == call["phase"], (name, prop)
