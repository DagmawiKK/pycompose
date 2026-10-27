"""Shared search owns editing and expansion; nested declarations are data only."""

import pytest

from pycompose.contract.registry_elements import SlotRule
from pycompose.core.node import Node
from pycompose.errors import ComponentRegistryError, IrValidationError
from pycompose.ir import emit_ir, to_dict, validate_ir
from pycompose.ir.generated_validators import REGISTRY
from pycompose.state import State
from pycompose.values import Dp, RoundedCornerShape


def owner(**overrides: object) -> Node:
    """A minimal owner with one collapsed and one expanded input declaration."""
    from pycompose.m3 import (
        ExpandedDockedSearchBar,
        SearchBarStateInputField,
        StatefulSearchBar,
    )

    props: dict[str, object] = {
        "id": "search",
        "text": "compose",
        "selection_start": 7,
        "selection_end": 7,
        "revision": 0,
        "on_edit": "submit",
        "expanded": False,
        "on_expanded_change": "submit",
        "input_field": SearchBarStateInputField(id="collapsed", on_search="submit"),
        "expanded_bar": ExpandedDockedSearchBar(
            id="expanded",
            input_field=SearchBarStateInputField(
                id="expanded.input", on_search="submit"
            ),
        ),
    }
    props.update(overrides)
    return StatefulSearchBar(**props)  # type: ignore[arg-type]


def test_owner_emits_distinct_collapsed_and_expanded_input_slots() -> None:
    """One node states the shared editing value; each surface declares only its slot."""
    from pycompose.m3 import ExpandedDockedSearchBar, SearchBarStateInputField, Text

    candidate = emit_ir(
        State(
            root=owner(
                expanded_bar=ExpandedDockedSearchBar(
                    id="expanded",
                    input_field=SearchBarStateInputField(
                        id="expanded.input", on_search="submit"
                    ),
                    content=Text(id="result", text="A result"),
                )
            )
        ),
        "1.23.0",
    )
    assert validate_ir(candidate).snapshot is candidate
    wire = to_dict(candidate)["root"]
    assert wire["type"] == "StatefulSearchBar"
    assert wire["props"] == {
        "text": "compose",
        "selectionStart": 7,
        "selectionEnd": 7,
        "revision": 0,
        "onEdit": "submit",
        "expanded": False,
        "onExpandedChange": "submit",
    }
    assert [child["slot"] for child in wire["children"]] == [
        "expandedBar",
        "inputField",
    ]
    collapsed = next(
        child for child in wire["children"] if child["slot"] == "inputField"
    )
    expanded = next(
        child for child in wire["children"] if child["slot"] == "expandedBar"
    )
    assert collapsed["type"] == "SearchBarStateInputField"
    assert collapsed["props"] == {"onSearch": "submit"}
    assert expanded["type"] == "ExpandedDockedSearchBar"
    assert [child.get("slot") for child in expanded["children"]] == [None, "inputField"]
    assert expanded["children"][0]["props"] == {"text": "A result"}
    assert expanded["children"][1]["type"] == "SearchBarStateInputField"
    assert expanded["children"][1]["props"] == {"onSearch": "submit"}


def test_full_screen_surface_is_the_same_owner_contract() -> None:
    """The dialog variant shares the owner's state exactly like the docked one."""
    from pycompose.m3 import ExpandedFullScreenSearchBar, SearchBarStateInputField

    candidate = emit_ir(
        State(
            root=owner(
                expanded_bar=ExpandedFullScreenSearchBar(
                    id="expanded",
                    collapsed_shape=RoundedCornerShape(Dp(28)),
                    input_field=SearchBarStateInputField(
                        id="expanded.input", on_search="submit"
                    ),
                )
            )
        ),
        "1.23.0",
    )
    assert validate_ir(candidate).snapshot is candidate
    wire = to_dict(candidate)["root"]
    expanded = next(
        child for child in wire["children"] if child["slot"] == "expandedBar"
    )
    assert expanded["type"] == "ExpandedFullScreenSearchBar"
    assert expanded["props"] == {
        "collapsedShape": {
            "type": "RoundedCornerShape",
            "size": {"type": "Dp", "value": 28},
        }
    }
    assert [child["slot"] for child in expanded["children"]] == ["inputField"]


def test_the_owner_declares_the_search_family_and_a_host_slot() -> None:
    """The schema names the shared state family and the slot the host composes."""
    spec = REGISTRY.components["StatefulSearchBar"]
    assert spec.state is not None
    assert spec.state.kind == "search"
    assert spec.state.value == "expanded"
    assert spec.state.report == "onExpandedChange"
    assert spec.slots["expandedBar"].host
    assert spec.slots["expandedBar"].native is None
    assert not spec.slots["inputField"].host
    assert spec.slots["inputField"].native == "inputField"


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


@pytest.mark.parametrize(
    ("prop", "value"),
    [
        ("selectionStart", -1),
        ("selectionEnd", -1),
        ("revision", -1),
        ("selectionStart", 2147483648),
        ("selectionEnd", 2147483648),
        ("revision", 9223372036854775808),
    ],
)
def test_out_of_range_owner_coordinates_are_rejected(prop: str, value: int) -> None:
    """The owner carries the same native bounds as the standalone stateful field."""
    props: dict[str, object] = {
        "text": "compose",
        "selectionStart": 7,
        "selectionEnd": 7,
        "revision": 0,
        "onEdit": "submit",
        "expanded": False,
        "onExpandedChange": "submit",
    }
    props[prop] = value
    with pytest.raises(IrValidationError):
        validate_ir(
            emit_ir(
                State(root=Node(id="search", type="StatefulSearchBar", props=props)),
                "1.23.0",
            )
        )


def test_the_owner_requires_the_whole_editing_projection() -> None:
    """A shared owner without its text cannot construct the native editing state."""
    with pytest.raises(IrValidationError):
        validate_ir(
            emit_ir(
                State(
                    root=Node(
                        id="search",
                        type="StatefulSearchBar",
                        props={
                            "expanded": False,
                            "onExpandedChange": "submit",
                        },
                    )
                ),
                "1.23.0",
            )
        )


def test_expansion_is_optional_so_native_gestures_can_own_it() -> None:
    """An owner that states no expansion still shares editing and reports gestures."""
    from pycompose.m3 import SearchBarStateInputField, StatefulSearchBar

    candidate = emit_ir(
        State(
            root=StatefulSearchBar(
                id="search",
                text="compose",
                selection_start=7,
                selection_end=7,
                revision=0,
                on_edit="submit",
                on_expanded_change="submit",
                input_field=SearchBarStateInputField(
                    id="collapsed", on_search="submit"
                ),
            )
        ),
        "1.23.0",
    )
    assert validate_ir(candidate).snapshot is candidate
    wire = to_dict(candidate)["root"]
    assert "expanded" not in wire["props"]
    assert wire["props"]["onExpandedChange"] == "submit"


def test_a_state_field_without_an_owner_still_emits_for_host_diagnosis() -> None:
    """The wire is structural; the host reports a missing owner instead of guessing."""
    from pycompose.m3 import SearchBarStateInputField

    candidate = emit_ir(
        State(root=SearchBarStateInputField(id="orphan", on_search="submit")),
        "1.23.0",
    )
    assert validate_ir(candidate).snapshot is candidate
    assert to_dict(candidate)["root"]["type"] == "SearchBarStateInputField"
