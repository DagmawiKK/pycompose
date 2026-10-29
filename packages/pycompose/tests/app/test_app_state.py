"""Typed app state: the codec derived from a declared shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pytest

from pycompose.errors import StateError
from pycompose.material3 import Text
from pycompose.state import AppState, State, Store
from pycompose.utils.json_canonical import freeze_json, thaw_json


class Filter(AppState):
    """A declared state with one of every shape worth carrying.

    Attributes:
        count: An integer, which must never accept a bool.
        title: A string.
        ratio: A float that must accept an int.
        done: A boolean.
        tags: A list of strings.
        rows: A list of nested dataclasses.
        choice: A literal.
        parent: An optional nested state.
        flag: An optional boolean.
    """

    count: int = 0
    title: str = ""
    ratio: float = 0.0
    done: bool = False
    tags: tuple[str, ...] = ()
    rows: list[Row] = field(default_factory=list)
    choice: Literal["all", "active"] = "all"
    parent: Parent | None = None
    flag: bool | None = None


class Countly(AppState):
    """A state with one required integer.

    Attributes:
        count: The integer.
    """

    count: int


class Inner(AppState):
    """A nested declared state.

    Attributes:
        value: Its one field.
    """

    value: int = 0


class Outer(AppState):
    """A state holding a nested declared state.

    Attributes:
        inner: The nested state.
        name: A plain field beside it.
    """

    inner: Inner = Inner()  # type: ignore[valid-type]
    name: str = ""


@dataclass(frozen=True)
class Row:
    """A nested plain dataclass.

    Attributes:
        id: Its identity.
        label: Its text.
    """

    id: int
    label: str


@dataclass(frozen=True)
class Parent:
    """A nested plain dataclass reached through an optional field.

    Attributes:
        name: Its name.
    """

    name: str = ""


def _state(**values: Any) -> State:
    """Return a State carrying one typed app value.

    Args:
        **values: Fields of the AppState.

    Returns:
        A snapshot whose data came from the declared state.
    """
    return State(root=Text(id="t", text="ok"), app=Filter(**values))


# ---------------------------------------------------------------------------
# Declaration
# ---------------------------------------------------------------------------


def test_a_subclass_is_already_a_frozen_dataclass() -> None:
    value = Filter(count=1)
    assert value.count == 1
    with pytest.raises(Exception):  # noqa: B017 -- frozen dataclass error
        value.count = 2  # type: ignore[misc]
    assert value.evolve(count=2).count == 2
    assert value.count == 1


def test_declared_state_publishes_camel_case_json() -> None:
    # State.data is the frozen form, so arrays arrive as tuples; what crosses the
    # wire is the thawed JSON below.
    assert thaw_json(dict(_state(count=3, title="hi").data or {})) == {
        "count": 3,
        "title": "hi",
        "ratio": 0.0,
        "done": False,
        "tags": [],
        "rows": [],
        "choice": "all",
        "parent": None,
        "flag": None,
    }


def test_typed_state_and_hand_written_data_are_interchangeable() -> None:
    typed = _state(count=7)
    plain = State(root=Text(id="t", text="ok"), data={"count": 7, "title": "hi"})
    # Both publish the same JSON, so persistence cannot tell them apart.
    assert set(typed.data or {}) >= set(plain.data or {})


def test_declaring_both_data_and_app_is_rejected() -> None:
    with pytest.raises(StateError, match="both"):
        State(root=Text(id="t", text="ok"), data={}, app=Filter())


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


def test_a_state_survives_a_round_trip_through_frozen_json() -> None:
    original = Filter(
        count=2,
        title="Groceries",
        ratio=1.5,
        done=True,
        tags=("a", "b"),
        rows=[Row(id=1, label="first")],
        choice="active",
        parent=Parent(name="p"),
        flag=False,
    )
    published = State(root=Text(id="t", text="ok"), app=original).data or {}

    # Straight back out of a snapshot, where the freeze has turned the arrays
    # into tuples. This is the case that silently deleted notes before.
    rebuilt = Filter.codec.decode(freeze_json(dict(published)))
    assert rebuilt == original
    assert isinstance(rebuilt.tags, tuple)
    assert isinstance(rebuilt.rows, list)
    assert rebuilt.rows[0] == Row(id=1, label="first")


def test_a_state_survives_a_round_trip_through_parsed_json() -> None:
    import json

    original = Filter(count=5, tags=("x",), rows=[Row(id=2, label="y")])
    # What the host hands back is parsed JSON: lists, plain objects, no freeze.
    wire = json.loads(json.dumps(thaw_json(dict(_state(count=5).data or {}))))
    rebuilt = Filter.codec.decode(wire)
    assert rebuilt.count == 5
    assert (
        Filter.codec.decode(
            json.loads(
                json.dumps(
                    thaw_json(
                        dict(
                            State(root=Text(id="t", text="o"), app=original).data or {}
                        )
                    )
                )
            )
        )
        == original
    )


def test_snake_case_keys_are_accepted_on_the_way_back() -> None:
    assert Filter.codec.decode({"count": 4, "title": "t"}) == Filter(count=4, title="t")


# ---------------------------------------------------------------------------
# Types are enforced
# ---------------------------------------------------------------------------


def test_an_int_field_will_not_hold_a_bool() -> None:
    with pytest.raises(StateError, match="count"):
        Filter.codec.decode({"count": True})
    with pytest.raises(StateError, match="cannot hold"):
        State(root=Text(id="t", text="ok"), app=Countly(count=True))  # type: ignore[arg-type]


def test_a_float_field_accepts_an_int() -> None:
    assert Filter.codec.decode({"ratio": 3}) == Filter(ratio=3.0)


def test_a_bool_field_will_not_hold_an_int() -> None:
    with pytest.raises(StateError, match="done"):
        Filter.codec.decode({"done": 1})


def test_a_literal_field_will_not_hold_anything_else() -> None:
    with pytest.raises(StateError, match="choice"):
        Filter.codec.decode({"choice": "nonsense"})


def test_an_unknown_field_is_rejected_rather_than_dropped() -> None:
    with pytest.raises(StateError, match="no field"):
        Filter.codec.decode({"nonexistent": 1})


def test_a_missing_required_field_is_rejected() -> None:
    class Required(AppState):
        must: str

    with pytest.raises(StateError, match="missing"):
        Required.codec.decode({})


def test_data_that_is_not_an_object_is_rejected() -> None:
    with pytest.raises(StateError, match="must be an object"):
        Filter.codec.decode([1, 2])


# ---------------------------------------------------------------------------
# Nesting
# ---------------------------------------------------------------------------


def test_nested_declared_state_round_trips() -> None:
    decoded = Outer.codec.decode({"inner": {"value": 9}, "name": "n"})
    assert decoded == Outer(inner=Inner(value=9), name="n")
    assert decoded.inner.value == 9


def test_nested_plain_dataclass_round_trips() -> None:
    decoded = Filter.codec.decode({"rows": [{"id": 1, "label": "a"}]})
    assert decoded.rows == [Row(id=1, label="a")]


def test_a_list_field_checks_its_elements_not_just_its_shape() -> None:
    # list[Row] must not quietly accept a list of anything at all.
    with pytest.raises(StateError, match="rows"):
        Filter.codec.decode({"rows": [1, 2, 3]})
    with pytest.raises(StateError, match="tags"):
        Filter.codec.decode({"tags": [1]})


def test_a_dict_field_checks_its_values() -> None:
    class Scores(AppState):
        table: dict[str, int] = field(default_factory=dict)

    assert Scores.codec.decode({"table": {"a": 1}}) == Scores(table={"a": 1})
    with pytest.raises(StateError, match="table"):
        Scores.codec.decode({"table": {"a": "one"}})


def test_a_nested_dataclass_missing_a_required_field_is_rejected() -> None:
    with pytest.raises(StateError, match="missing"):
        Filter.codec.decode({"rows": [{"label": "a"}]})


def test_an_optional_field_accepts_null() -> None:
    assert Filter.codec.decode({"parent": None}).parent is None


# ---------------------------------------------------------------------------
# Declaration mistakes
# ---------------------------------------------------------------------------


def test_an_unsupported_field_type_is_refused_on_first_use() -> None:
    class Bad(AppState):
        when: object

    with pytest.raises(StateError, match="unsupported"):
        _ = Bad.codec


def test_a_subclass_never_inherits_its_parentscodec() -> None:
    class Parent(AppState):
        count: int = 0

    class Child(Parent):
        title: str = ""

    # Parent's codec knows nothing about ``title``; Child's knows about both.
    assert Parent.codec.decode({"count": 1}) == Parent(count=1)
    assert Child.codec.decode({"count": 1, "title": "t"}) == Child(count=1, title="t")
    with pytest.raises(StateError, match="no field"):
        Parent.codec.decode({"title": "t"})  # type: ignore[call-overload]


def test_store_round_trips_a_typed_state_through_a_real_snapshot() -> None:
    from handlers import Handlers

    from pycompose.bridge import BridgeSurface

    bridge = BridgeSurface(Store(_state(count=1)), Handlers())
    assert bridge.expose_latest_snapshot() is not None
    assert bridge.expose_latest_error() == ""
    rebuilt = Filter.codec.decode(
        __import__("json").loads(bridge.expose_latest_snapshot() or "{}")["metadata"][
            "data"
        ]
    )
    assert rebuilt.count == 1
