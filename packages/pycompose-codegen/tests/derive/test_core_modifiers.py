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
