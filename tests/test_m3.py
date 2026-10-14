"""Generated native component imports through the public contract seam."""

import pytest

from pycompose.core import Node
from pycompose.ir import emit_ir, to_json_bytes, validate_ir
from pycompose.state import State


def test_imported_builtins_preserve_the_native_contract() -> None:
    from pycompose.m3 import Column, Modifier, Text

    node = Column(
        id="screen",
        horizontal_alignment="center",
        modifier=Modifier().padding(8).fill_max_width(),
        children=(Text(id="name", text="Ada"),),
    )
    assert isinstance(node, Node)
    candidate = emit_ir(State(root=node), "1.0.0")
    assert validate_ir(candidate).snapshot is candidate
    assert to_json_bytes(candidate) == (
        b'{"root":{"children":[{"id":"root.name","props":{"text":"Ada"},'
        b'"type":"Text"}],"id":"root","props":{"horizontalAlignment":"center",'
        b'"modifier":{"operations":[{"type":"padding","value":8},'
        b'{"fraction":1,"type":"fillMaxWidth"}]}},"type":"Column"},'
        b'"schemaVersion":"1.0.0","version":"0.1.0"}'
    )


def test_generated_interfaces_preserve_defaults_and_slots() -> None:
    from pycompose.m3 import Button, LazyColumn, Scaffold, Text

    button = Button(id="add", text="Add", on_click="increment")
    assert button.props.to_wire() == {"text": "Add", "onClick": "increment"}
    text = Text(id="name", text="Ada")
    assert LazyColumn(id="list", items=(text,)).children == (text,)
    assert Scaffold(id="screen", content=text).children == (text,)
    with pytest.raises(TypeError, match="unexpected keyword"):
        Text(id="name", text="Ada", typo=True)
    with pytest.raises(TypeError, match="text"):
        Text(id="name")


def test_generated_enum_props_still_validate_at_runtime() -> None:
    from pycompose.errors import IrValidationError
    from pycompose.m3 import Text

    with pytest.raises(IrValidationError, match="invalid prop"):
        Text(id="name", text="Ada", style="unsupported")
