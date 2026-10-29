"""The host-owned state projection: Python states the value, the host drives it.

A component that needs native state -- a drawer's open/closed, a sheet's
expansion -- declares in its schema entry which native parameter the host's
remembered holder fills, which prop carries the app's desired value, and which
prop reports the settled value back as an action. The holder belongs to the
host and to one node id, so pulling a snapshot restarts no gesture in flight and
a change the app did not cause still reaches it.

These tests pin the Python half of that contract: how the desired value and its
report reach the wire, how the adapter fills the parameter, and what the codegen
refuses rather than guesses.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pycompose_codegen.emit.state_anchors import SWIPE_VALUES
from pycompose_codegen.emit.state_rules import STATE_VALUE_TYPES

from pycompose.contract.catalog import REGISTRY
from pycompose.core.node import Node
from pycompose.material3 import ModalBottomSheet, ModalNavigationDrawer, Text
from pycompose.state import State
from pycompose.wire import emit_ir, to_dict, validate_ir
from pycompose.wire.validator import validate_prop

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "schema" / "catalog.lock.json"

CATALOG = json.loads(SCHEMA_PATH.read_text())
"""The parsed catalog, so the wire tests state the version they are tested at."""


@pytest.mark.parametrize("value", [-1, 2**31])
@pytest.mark.parametrize(
    ("component", "prop"), [("Slider", "steps"), ("LazyColumn", "firstVisibleIndex")]
)
def test_state_integers_cannot_overflow_or_violate_native_bounds(
    component: str, prop: str, value: int
) -> None:
    """The wire refuses native Int failures before the host can construct one.

    Args:
        component: Registered stateful component.
        prop: Integer consumed by its holder.
        value: Negative or overflowing native integer.
    """
    assert not validate_prop(value, REGISTRY.components[component].props[prop])


STATEFUL = "ModalNavigationDrawer"

GATED = "ModalBottomSheet"


def snapshot(root: Node) -> dict:
    """Emit, validate and serialize one root.

    Args:
        root: The tree to publish.

    Returns:
        The canonical wire snapshot.
    """
    candidate = emit_ir(State(root=root), CATALOG["schemaVersion"])
    assert validate_ir(candidate).snapshot is candidate
    return to_dict(candidate)


def components() -> dict[str, Any]:
    """Return the schema's component entries, keyed by name.

    Returns:
        Every component entry in the catalog lock.
    """
    return CATALOG["components"]


# ---------------------------------------------------------------------------
# The desired value and its report are ordinary props
# ---------------------------------------------------------------------------


def test_the_generated_constructor_states_the_desired_value() -> None:
    """The value and the report are props; the wire carries them camelCase."""
    wire = snapshot(
        ModalNavigationDrawer(
            id="drawer",
            open=True,
            on_open_change="submit",
            children=[Text(id="body", text="Body")],
            drawer=[Text(id="panel", text="Menu")],
        )
    )
    props = wire["root"]["props"]
    assert props["open"] is True
    assert props["onOpenChange"] == "submit"
    slots = {
        child["props"]["text"]: child.get("slot") for child in wire["root"]["children"]
    }
    assert slots == {"Body": None, "Menu": "drawer"}


def test_an_undeclared_desired_value_is_omitted_from_the_wire() -> None:
    """Absent is not false: the app said nothing, so nothing is reconciled."""
    wire = snapshot(
        ModalNavigationDrawer(id="drawer", on_open_change="submit", children=[])
    )
    assert "open" not in wire["root"]["props"]


def test_a_sheet_states_its_desired_value_and_reaches_its_handle_slot() -> None:
    """The same protocol on a modal surface, plus its own named slot."""
    wire = snapshot(
        ModalBottomSheet(
            id="sheet",
            open=True,
            on_open_change="submit",
            children=[Text(id="body", text="Body")],
            drag_handle=[Text(id="handle", text="Handle")],
        )
    )
    props = wire["root"]["props"]
    assert props["open"] is True
    assert props["onOpenChange"] == "submit"
    slots = {
        child["props"]["text"]: child.get("slot") for child in wire["root"]["children"]
    }
    assert slots == {"Body": None, "Handle": "dragHandle"}


# ---------------------------------------------------------------------------
# Every declaration agrees with the props it names
# ---------------------------------------------------------------------------


def test_every_declared_state_names_a_typed_value_and_a_matching_report() -> None:
    """Scalar families report one value; swipe and editing use closed shapes.

    A drawer's desired value is a boolean, a scroll offset a number, a list's
    first visible index an integer; whichever it is, the settled report fills a
    payload field of the same type, so the host never guesses which scalar the
    observation carries. A swipe's three anchors are an enum and its report is
    the lowerCamel string spelling of the anchor it reached.
    """
    for name, entry in sorted(components().items()):
        state = entry.get("state")
        if state is None or state["kind"] == "properties":
            # A derived family's props are its holder's (test_property_holders).
            continue
        props = entry["props"]
        assert state["native"] not in props, name
        value = props[state["value"]]
        if state["kind"] == "textInput":
            assert value["type"] == "string", name
            assert value["required"], name
            report = props[state["report"]]
            assert report["required"], name
            assert report["payload"] == [
                {"name": "text", "type": "string"},
                {"name": "selectionStart", "type": "integer"},
                {"name": "selectionEnd", "type": "integer"},
                {"name": "revision", "type": "integer"},
            ], name
            continue
        if state["kind"] == "swipe":
            assert value["type"] == "enum", name
            assert value["values"] == list(SWIPE_VALUES), name
            assert not value.get("required"), name
            report = props[state["report"]]
            assert report["type"] == "actionId", name
            assert [field["type"] for field in report["payload"]] == ["string"], name
            assert state["value"] in entry.get("reshaped", []), name
            assert state["report"] in entry.get("reshaped", []), name
            continue
        assert value["type"] in STATE_VALUE_TYPES, name
        assert not value.get("required"), name
        report = props[state["report"]]
        assert report["type"] == "actionId", name
        assert [field["type"] for field in report["payload"]] == [value["type"]], name
        # Neither is a native parameter of its own, so both are recorded as
        # reshaped rather than silently dropped.
        assert state["value"] in entry.get("reshaped", []), name
        assert state["report"] in entry.get("reshaped", []), name


def test_every_state_kind_is_a_vocabulary_member() -> None:
    """The declaration never invents a kind the host cannot create and drive."""
    from pycompose.contract.registry_types import STATE_KINDS

    for name, entry in sorted(components().items()):
        state = entry.get("state")
        if state is not None:
            assert state["kind"] in {*STATE_KINDS, "properties"}, name


def test_every_declared_dismissal_names_an_unclaimed_parameter() -> None:
    """A completed callback is not a prop, and not anyone else's parameter."""
    for name, entry in sorted(components().items()):
        state = entry.get("state") or {}
        dismiss = state.get("dismiss")
        if dismiss is None:
            continue
        assert dismiss != state["native"], name
        assert dismiss not in entry["props"], name
        assert dismiss != entry["children"].get("native", "content"), name
        assert dismiss not in {
            slot["native"] for slot in entry.get("slots", {}).values()
        }, name


# ---------------------------------------------------------------------------
# The adapter fills the parameter; the props are not native ones
# ---------------------------------------------------------------------------


def test_every_family_table_names_known_state_kinds() -> None:
    """A gate, attach or constructor decision for an unknown family is a typo."""
    from pycompose_codegen.emit.adapters.state import GATED_STATES
    from pycompose_codegen.emit.state_families import (
        STATE_ATTACH_GATES,
        STATE_CONSTRUCTOR_PROPS,
    )

    from pycompose.contract.registry_types import STATE_KINDS

    assert set(STATE_KINDS) >= GATED_STATES
    assert set(STATE_ATTACH_GATES) <= set(STATE_KINDS)
    assert set(STATE_CONSTRUCTOR_PROPS) <= set(STATE_KINDS)


# ---------------------------------------------------------------------------
# The codegen refuses a state it cannot render faithfully
# ---------------------------------------------------------------------------


def load_with(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """Validate the catalog after one deliberate change.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch fixture.
        mutate: Applies the change to the loaded registry.
    """
    from pycompose_codegen.emit import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    mutate(registry)
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    main.load_registry()


def _state(registry: dict[str, Any], component: str = STATEFUL) -> dict[str, Any]:
    """Return one mutably loaded state entry.

    Args:
        registry: The loaded catalog.
        component: Component owning the state.

    Returns:
        The state's raw entry, for the caller to break.
    """
    return registry["components"][component]["state"]


def _payload(registry: dict[str, Any], prop: str, component: str = STATEFUL) -> dict:
    """Return one reported prop's payload field.

    Args:
        registry: The loaded catalog.
        prop: The reporting prop whose payload to break.
        component: Component owning the prop.

    Returns:
        The payload field, for the caller to break.
    """
    return registry["components"][component]["props"][prop]["payload"][0]


def _with_scrollable(registry: dict[str, Any], prop_type: str) -> None:
    """Give the drawer a scroll state with one deliberately typed gate prop.

    Args:
        registry: The loaded catalog.
        prop_type: The prop type to declare the gate with.
    """
    _state(registry).update(kind="scroll")
    registry["components"][STATEFUL]["props"]["scrollable"] = {"type": prop_type}


def test_a_numeric_desired_value_and_a_family_gate_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A number can drive a family the way a boolean drives a drawer.

    The declaration itself is type-polymorphic: which scalar a family drives
    is the family's business, and the report answers in the same scalar.
    """

    def mutate(registry: dict[str, Any]) -> None:
        props = registry["components"][STATEFUL]["props"]
        props["open"]["type"] = "number"
        props["onOpenChange"]["payload"][0]["type"] = "number"

    load_with(tmp_path, monkeypatch, mutate)


def test_a_modifier_riding_family_carries_its_boolean_gate_prop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A family whose holder rides a modifier gates the attach with a boolean."""
    load_with(
        tmp_path,
        monkeypatch,
        lambda registry: _with_scrollable(registry, "boolean"),
    )


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        (
            lambda registry: registry["components"][STATEFUL].update(state=3),
            "must be an object",
        ),
        (
            lambda registry: _state(registry).update(unknown=True),
            "unknown keys",
        ),
        (
            lambda registry: _state(registry).update(kind="dialog"),
            "unknown state kind",
        ),
        (
            lambda registry: _state(registry).update(native="open"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(native="drawerContent"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(native="content"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(dismiss="open"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(dismiss="drawerState"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(dismiss="drawerContent"),
            "repeats another parameter",
        ),
        (
            lambda registry: _state(registry).update(dismiss=3),
            "must be a parameter name",
        ),
        (
            lambda registry: _state(registry).update(kind="slider"),
            "needs the props valueRange, steps",
        ),
        (
            lambda registry: _with_scrollable(registry, "number"),
            "'scrollable' must be a boolean",
        ),
        (
            lambda registry: registry["components"][STATEFUL]["props"]["open"].update(
                type="string"
            ),
            "must be a boolean, number or integer",
        ),
        (
            lambda registry: registry["components"][STATEFUL]["props"]["open"].update(
                type="number"
            ),
            "needs one number payload field",
        ),
        (
            lambda registry: _state(registry).update(value="onOpenChange"),
            "must be a boolean, number or integer",
        ),
        (
            lambda registry: _state(registry).update(value="missing"),
            "must name one of the props",
        ),
        (
            lambda registry: _state(registry).update(report="open"),
            "must be an actionId",
        ),
        (
            lambda registry: _state(registry).update(report="missing"),
            "must name one of the props",
        ),
        (
            lambda registry: _payload(registry, "onOpenChange").update(type="string"),
            "needs one boolean payload field",
        ),
        (
            lambda registry: _payload(registry, "onOpenChange").update(name="Value"),
            "needs one boolean payload field",
        ),
    ],
)
def test_the_codegen_refuses_an_unrenderable_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    break_it: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    """A state the generator cannot drive faithfully is refused, not guessed.

    An adapter emitted from a half-understood declaration compiles and then
    drives the wrong value or reports none at all, which is worse than not
    building at all.
    """
    with pytest.raises(SystemExit, match=expected):
        load_with(tmp_path, monkeypatch, break_it)


def test_a_swipe_names_the_closed_enum_and_its_string_report() -> None:
    """The swipe's three anchors are the whole value set, not an open string."""
    entry = components()["SwipeToDismissBox"]
    assert entry["state"] == {
        "native": "state",
        "kind": "swipe",
        "value": "value",
        "report": "onValueChange",
    }
    assert entry["props"]["value"]["values"] == list(SWIPE_VALUES)
    assert entry["props"]["onValueChange"]["payload"] == [
        {"name": "value", "type": "string"}
    ]


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        (
            lambda registry: registry["components"]["SwipeToDismissBox"]["props"][
                "value"
            ].update(type="string"),
            "must be an enum with the values",
        ),
        (
            lambda registry: registry["components"]["SwipeToDismissBox"]["props"][
                "value"
            ].update(values=["settled", "startToEnd"]),
            "must be an enum with the values",
        ),
        (
            lambda registry: registry["components"]["SwipeToDismissBox"]["props"][
                "value"
            ].update(required=True),
            "must be optional",
        ),
        (
            lambda registry: registry["components"]["SwipeToDismissBox"]["props"][
                "onValueChange"
            ]["payload"][0].update(type="boolean"),
            "needs one string payload field",
        ),
    ],
)
def test_the_codegen_refuses_an_unrenderable_swipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    break_it: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    """A swipe family the host cannot map to its closed anchors is refused."""
    with pytest.raises(SystemExit, match=expected):
        load_with(tmp_path, monkeypatch, break_it)


def test_the_codegen_refuses_a_second_reported_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One boolean is the whole report; two fields would mean the host guesses."""
    with pytest.raises(SystemExit, match="needs one boolean payload field"):
        load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"][STATEFUL]["props"]["onOpenChange"][
                "payload"
            ].append({"name": "extra", "type": "boolean"}),
        )


# ---------------------------------------------------------------------------
# The runtime registry carries the declaration, not just the codegen
# ---------------------------------------------------------------------------


def test_the_runtime_registry_round_trips_the_state() -> None:
    """The registry type keeps the declaration a schema reader can trust."""
    from pycompose.contract.registry_types import ComponentSpec
    from pycompose.errors import ComponentRegistryError

    state = {
        "native": "drawerState",
        "kind": "drawer",
        "value": "open",
        "report": "onOpenChange",
    }
    spec = ComponentSpec.from_mapping(
        STATEFUL,
        {
            "category": "layout",
            "stability": "stable",
            "props": {},
            "children": {"allowed": True},
            "state": state,
        },
    )
    assert spec.state is not None
    assert spec.state.kind == "drawer"
    assert spec.to_mapping()["state"] == state
    dismissed = {**state, "dismiss": "onDismissRequest"}
    spec = ComponentSpec.from_mapping(
        STATEFUL,
        {
            "category": "layout",
            "stability": "stable",
            "props": {},
            "children": {"allowed": True},
            "state": dismissed,
        },
    )
    assert spec.state is not None
    assert spec.state.dismiss == "onDismissRequest"
    assert spec.to_mapping()["state"] == dismissed
    with pytest.raises(ComponentRegistryError, match="'dismiss' must be a name"):
        ComponentSpec.from_mapping(
            STATEFUL,
            {
                "category": "layout",
                "stability": "stable",
                "props": {},
                "children": {"allowed": True},
                "state": {**state, "dismiss": 3},
            },
        )
    with pytest.raises(ComponentRegistryError, match="unknown state kind"):
        ComponentSpec.from_mapping(
            STATEFUL,
            {
                "category": "layout",
                "stability": "stable",
                "props": {},
                "children": {"allowed": True},
                "state": {**state, "kind": "dialog"},
            },
        )
    with pytest.raises(ComponentRegistryError, match="'native' must be a name"):
        ComponentSpec.from_mapping(
            STATEFUL,
            {
                "category": "layout",
                "stability": "stable",
                "props": {},
                "children": {"allowed": True},
                "state": {"native": 3},
            },
        )
