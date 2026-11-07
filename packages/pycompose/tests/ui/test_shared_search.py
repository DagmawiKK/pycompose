"""A search composes from generated parts: the bar owns its state, others share it."""

import pytest

from pycompose.errors import ComponentRegistryError, IrValidationError
from pycompose.host.wire import emit_ir, validate_ir
from pycompose.model.catalog.elements import SlotRule
from pycompose.model.catalog.lock import REGISTRY
from pycompose.model.nodes.node import Node
from pycompose.model.snapshot import Snapshot

SEARCH_BAR_STATE = "androidx.compose.material3.SearchBarState"


def search(**overrides: object) -> Node:
    """A bar, its input field, and a full-screen surface sharing the bar's state."""
    from pycompose.ui import (
        Column,
        ExpandedFullScreenSearchBar,
        SearchBarStateInputField,
        StatefulSearchBar,
        Text,
    )

    def field(id: str) -> Node:
        return SearchBarStateInputField(
            id=id,
            search_bar_state="bar",
            text="compose",
            selection_start=7,
            selection_end=7,
            on_edit="submit",
            on_search="submit",
        )

    bar: dict[str, object] = {
        "id": "bar",
        "value": "collapsed",
        "on_value_change": "submit",
        "input_field": field("collapsed"),
    }
    bar.update(overrides)
    return Column(
        children=[
            StatefulSearchBar(**bar),  # type: ignore[arg-type]
            ExpandedFullScreenSearchBar(
                id="expanded",
                state="bar",
                input_field=field("expanded.input"),
                children=[Text(id="result", text="A result")],
            ),
        ]
    )


def test_a_search_composes_from_its_generated_parts() -> None:
    """The bar, its field and its surface each validate as ordinary nodes."""
    snapshot = emit_ir(Snapshot(root=search()), "1.23.0")
    assert validate_ir(snapshot).snapshot is snapshot


def test_the_bar_owns_its_state_and_the_others_name_it() -> None:
    """The bar's state is anchored; the field and the surface share it by node id."""
    bar = REGISTRY.components["StatefulSearchBar"]
    assert bar.state is not None and bar.state.kind == "anchored"
    assert REGISTRY.components["ExpandedFullScreenSearchBar"].shared == {
        "state": SEARCH_BAR_STATE
    }
    assert REGISTRY.components["ExpandedDockedSearchBar"].shared == {
        "state": SEARCH_BAR_STATE
    }
    field = REGISTRY.components["SearchBarStateInputField"]
    assert field.state is not None and field.state.kind == "textInput"
    assert field.shared == {"searchBarState": SEARCH_BAR_STATE}


def test_a_shared_holder_must_name_its_owner() -> None:
    """A surface with no bar to share has no state to compose with."""
    with pytest.raises(IrValidationError):
        validate_ir(
            emit_ir(
                Snapshot(root=Node(id="expanded", type="ExpandedDockedSearchBar")),
                "1.23.0",
            )
        )


def test_expansion_is_optional_so_native_gestures_can_own_it() -> None:
    """A bar that states no value leaves expansion to its own gestures."""
    snapshot = emit_ir(Snapshot(root=search(value=None)), "1.23.0")
    assert validate_ir(snapshot).snapshot is snapshot


def test_a_host_slot_round_trips_without_a_native_parameter() -> None:
    """A host slot is one key; no native name is invented for it."""
    rule = SlotRule.from_mapping({"host": True}, where="search.expandedBar")
    assert rule.host
    assert rule.native is None
    assert rule.to_mapping() == {"host": True}


@pytest.mark.parametrize(
    "raw",
    [
        {"host": True, "native": "inputField"},
        {"host": False},
        {"host": "yes"},
        {"host": True, "nullable": True},
    ],
)
def test_a_host_slot_rejects_a_native_policy(raw: dict[str, object]) -> None:
    """Mixing host composition with a native parameter is not a slot shape."""
    with pytest.raises(ComponentRegistryError):
        SlotRule.from_mapping(raw, where="search.expandedBar")
