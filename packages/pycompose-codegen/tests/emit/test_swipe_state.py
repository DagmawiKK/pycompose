"""The swipe family: a closed three-anchor enum on one host-owned holder."""

from __future__ import annotations

import pytest
from test_state_projection import CATALOG, snapshot

from pycompose.material3 import SwipeToDismissBox, Text
from pycompose.model.catalog.lock import REGISTRY
from pycompose.model.nodes.node import Node
from pycompose.ui._rules import validate_prop


def box(**overrides: object) -> Node:
    """A swipe box with one content row and one background slot.

    Args:
        **overrides: Props replacing the fixture's defaults.

    Returns:
        The root node to publish.
    """
    props: dict[str, object] = {
        "id": "swipe",
        "background_content": Text(id="background", text="Delete"),
        "children": [Text(id="content", text="Row")],
    }
    props.update(overrides)
    return SwipeToDismissBox(**props)  # type: ignore[arg-type]


def test_the_swipe_family_is_closed_and_declares_a_string_report() -> None:
    """The three native anchors are the whole value set, never an open string."""
    spec = REGISTRY.components["SwipeToDismissBox"]
    assert spec.state is not None
    assert spec.state.kind == "swipe"
    assert spec.state.value == "value"
    assert spec.state.report == "onValueChange"
    value = spec.props["value"]
    assert value.type == "enum"
    assert value.values == ("settled", "startToEnd", "endToStart")
    assert not value.required
    report = spec.props["onValueChange"]
    assert report.type == "actionId"
    assert report.payload == (("value", "string"),)


def test_the_swipe_emits_its_anchor_and_background_slot() -> None:
    """The background is a named slot; content children stay ordinary children."""
    wire = snapshot(box(value="endToStart", on_value_change="submit"))["root"]
    assert wire["type"] == "SwipeToDismissBox"
    assert wire["props"] == {"value": "endToStart", "onValueChange": "submit"}
    assert [child.get("slot") for child in wire["children"]] == [
        None,
        "backgroundContent",
    ]
    assert wire["children"][0]["props"] == {"text": "Row"}
    assert wire["children"][1]["props"] == {"text": "Delete"}


@pytest.mark.parametrize("anchor", ["settled", "startToEnd", "endToStart"])
def test_each_closed_anchor_round_trips(anchor: str) -> None:
    """Every native anchor is a wire value the validator accepts."""
    wire = snapshot(box(value=anchor, on_value_change="submit"))["root"]
    assert wire["props"]["value"] == anchor


def test_omitting_the_anchor_leaves_the_swipe_to_gestures() -> None:
    """Neither the desired anchor nor the report is required by the family."""
    wire = snapshot(box())["root"]
    assert wire["props"] == {}


def test_the_validator_refuses_an_anchor_outside_the_closed_set() -> None:
    """A typo cannot become a fourth native state the host has no mapping for."""
    value = REGISTRY.components["SwipeToDismissBox"].props["value"]
    assert validate_prop("endToStart", value)
    assert not validate_prop("left", value)


def test_the_swipe_omits_the_native_dismiss_callback() -> None:
    """The settled report already carries the dismissal; no second callback."""
    entry = CATALOG["components"]["SwipeToDismissBox"]
    assert "dismiss" not in entry["state"]
    assert "onDismiss" not in entry["props"]


def test_the_swipe_booleans_keep_their_native_defaults() -> None:
    """Both directions and gestures start enabled unless the app says otherwise."""
    entry = CATALOG["components"]["SwipeToDismissBox"]
    for name in (
        "enableDismissFromStartToEnd",
        "enableDismissFromEndToStart",
        "gesturesEnabled",
    ):
        assert entry["props"][name] == {"type": "boolean", "default": True}


def test_the_background_and_content_are_row_scoped() -> None:
    """Both lambda parameters are RowScope slots, not plain content."""
    entry = CATALOG["components"]["SwipeToDismissBox"]
    assert entry["children"] == {
        "allowed": True,
        "kind": "content",
        "provides": "androidx.compose.foundation.layout.RowScope",
    }
    assert entry["slots"] == {
        "backgroundContent": {
            "native": "backgroundContent",
            "provides": "androidx.compose.foundation.layout.RowScope",
        }
    }
