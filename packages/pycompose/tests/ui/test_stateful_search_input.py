"""The state-based search field at the Python constructor-to-IR seam."""

import pytest

from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, to_dict, validate_ir
from pycompose.model.snapshot import Snapshot
from pycompose.ui import StatefulSearchBarInputField


def test_text_selection_and_revision_travel_in_one_snapshot() -> None:
    """Python states a complete editing value; no native object crosses the wire."""
    from pycompose.ui import Text

    candidate = emit_ir(
        Snapshot(
            root=StatefulSearchBarInputField(
                id="search",
                text="compose",
                selection_start=7,
                selection_end=2,
                revision=4,
                on_edit="submit",
                on_search="submit",
                expanded=False,
                on_expanded_change="submit",
                prefix=Text(id="prefix", text="Find"),
                suffix=Text(id="suffix", text="Now"),
            )
        ),
        "1.23.0",
    )
    assert validate_ir(candidate).snapshot is candidate
    wire = to_dict(candidate)["root"]
    assert wire["type"] == "StatefulSearchBarInputField"
    assert wire["props"] == {
        "text": "compose",
        "selectionStart": 7,
        "selectionEnd": 2,
        "revision": 4,
        "onEdit": "submit",
        "onSearch": "submit",
        "expanded": False,
        "onExpandedChange": "submit",
    }
    assert {child["slot"] for child in wire["children"]} == {"prefix", "suffix"}


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
def test_out_of_range_editing_coordinates_are_rejected(prop: str, value: int) -> None:
    """Native coordinates and revisions never wrap through unsigned coercion."""
    from pycompose.model.nodes.node import Node

    props = {
        "text": "compose",
        "selectionStart": 7,
        "selectionEnd": 7,
        "revision": 0,
        "onEdit": "submit",
        "onSearch": "submit",
        "expanded": False,
        "onExpandedChange": "submit",
    }
    props[prop] = value
    with pytest.raises(IrValidationError):
        validate_ir(
            emit_ir(
                Snapshot(
                    root=Node(
                        id="field", type="StatefulSearchBarInputField", props=props
                    )
                ),
                "1.23.0",
            )
        )
