"""Function props: a holder's factory asks the app's host function on the host.

An enum argument reaches the program as its wire spelling, compared by equality.
"""

from __future__ import annotations

import linecache
from typing import cast

import pytest

from pycompose.errors import IrValidationError
from pycompose.host.wire import emit_ir, validate_ir
from pycompose.model.canonical import thaw_json
from pycompose.model.catalog.lock import REGISTRY, SCHEMA_VERSION
from pycompose.model.programs.bound import validate_function_call
from pycompose.model.programs.functions import HostFunction
from pycompose.model.programs.refs import program_hash
from pycompose.model.snapshot import Snapshot
from pycompose.ui import ModalNavigationDrawer, Text, host
from pycompose.ui._props import validate_prop


def _compiled(name: str, source: str, **constants: object) -> HostFunction:
    """Compile one ``@host`` function from source the compiler can read."""
    scope: dict[str, object] = {"host": host, **constants}
    file = f"<{name}>"
    linecache.cache[file] = (len(source), None, source.splitlines(True), file)
    exec(compile(source, file, "exec"), scope)
    return cast("HostFunction", scope[name])


def test_an_enum_argument_is_its_spelling_compared_by_equality() -> None:
    source = (
        "from typing import Literal\n"
        "@host\n"
        "def keep(value: Literal['closed', 'open']) -> bool:\n"
        "    return value != CLOSED\n"
    )
    keep = _compiled("keep", source, CLOSED="closed")
    assert keep.to_wire() == {
        "type": "program",
        "params": ["string"],
        "result": "boolean",
        "body": {"op": "ne", "args": [{"arg": 0}, {"string": "closed"}]},
    }
    assert keep("open") and not keep("closed")


def _program(params: list[str], result: str, body: object) -> dict[str, object]:
    return {"type": "program", "params": params, "result": result, "body": body}


def test_a_function_prop_takes_the_hosts_arguments_then_its_bound_ones() -> None:
    keep = _program(
        ["string", "string"], "boolean", {"op": "ne", "args": [{"arg": 0}, {"arg": 1}]}
    )
    validate_function_call(
        {"type": "bound", "program": keep, "args": ["closed"]}, ("string",), "boolean"
    )
    with pytest.raises(IrValidationError, match="is not"):
        validate_function_call(keep, ("number",), "boolean")
    with pytest.raises(IrValidationError, match="bound arguments"):
        validate_function_call(
            {"type": "bound", "program": keep, "args": [1]}, ("string",), "boolean"
        )


def test_a_drawer_asks_the_apps_function_whether_it_may_settle() -> None:
    source = (
        "@host\n"
        "def stay_open(drawer_value: str) -> bool:\n"
        "    return drawer_value != 'closed'\n"
    )
    stay_open = _compiled("stay_open", source)
    prop = REGISTRY.components["ModalNavigationDrawer"].props["confirmStateChange"]

    assert prop.payload == (("drawerValue", "string"),) and prop.result == "boolean"
    assert validate_prop(stay_open.to_wire(), prop)
    node = ModalNavigationDrawer(
        Text(text="Body"), value="open", confirm_state_change=stay_open
    )
    # The program crosses once, by reference, and both validators judge it there.
    snapshot = emit_ir(Snapshot(root=node), SCHEMA_VERSION)
    assert validate_ir(snapshot).snapshot is snapshot
    assert thaw_json(snapshot.root.props.get("confirmStateChange")) == {
        "type": "ref",
        "hash": program_hash(stay_open.to_wire()),
    }
