"""An intent's contract at the bridge: what an event may supply, and what it may not."""

from __future__ import annotations

import json
from typing import Literal

import pytest

from pycompose.app import App, Destination, Intent, ViewModel
from pycompose.app.session import NavigationSession
from pycompose.bridge import BridgeSurface
from pycompose.errors import IrValidationError
from pycompose.m3 import Button, Column, Text, TextField
from pycompose.state import AppState, Store


class Note(AppState):
    title: str = ""
    picked: str = "none"
    due: int | None = 0


class Rename(Intent):
    note_id: int
    value: str


class Pick(Intent):
    value: Literal["red", "green"]


class SetDue(Intent):
    value: int | None


class NoteViewModel(ViewModel[Note]):
    def __init__(self) -> None:
        super().__init__(Note())

    def on_intent(self, intent: Intent) -> None:
        match intent:
            case Rename(note_id=7, value=value):
                self.state = self.state.evolve(title=value)
            case Pick(value=value):
                self.state = self.state.evolve(picked=value)
            case SetDue(value=value):
                self.state = self.state.evolve(due=value)


def screen(state: Note) -> Column:
    return Column(
        id="screen",
        children=[
            Text(id="state", text=f"{state.title}|{state.picked}|{state.due}"),
            TextField(
                id="title", value=state.title, on_value_change=Rename.bind(note_id=7)
            ),
            Button(id="red", text="Red", on_click=Pick(value="red")),
            Button(id="due", text="Due", on_click=SetDue),
        ],
    )


APP = App(start=Destination(lambda _container, _route: NoteViewModel(), screen))


@pytest.fixture
def bridge() -> BridgeSurface:
    session = NavigationSession(
        APP, None, "", "", report=lambda *_: None, signal=lambda: None
    )
    return BridgeSurface(Store(session.snapshot_state(None)), session)


def shown(bridge: BridgeSurface) -> str:
    root = json.loads(bridge.expose_latest_snapshot() or "{}")["root"]
    return root["children"][0]["props"]["text"]


def tap(bridge: BridgeSurface, node: str, prop: str, **payload: object) -> None:
    root = json.loads(bridge.expose_latest_snapshot() or "{}")["root"]
    paths = bridge.node_paths()
    target = next(c for c in root["children"] if paths[c["id"]].endswith(node))
    bridge.accept_action(json.dumps({**target["props"][prop], "payload": payload}))


def test_an_event_supplies_what_the_control_left_unbound(bridge: BridgeSurface) -> None:
    tap(bridge, "title", "onValueChange", value="Groceries")
    assert shown(bridge) == "Groceries|none|0"
    assert bridge.expose_latest_error() == ""


@pytest.mark.parametrize(
    "payload",
    [{}, {"value": 3}, {"value": None}, {"value": "x", "extra": 1}],
)
def test_an_event_that_breaks_the_contract_changes_nothing(
    bridge: BridgeSurface, payload: dict[str, object]
) -> None:
    before = bridge.expose_latest_snapshot()
    tap(bridge, "title", "onValueChange", **payload)
    assert bridge.expose_latest_snapshot() == before
    assert bridge.expose_latest_error() != ""


def test_an_event_cannot_override_what_the_control_bound(
    bridge: BridgeSurface,
) -> None:
    before = bridge.expose_latest_snapshot()
    tap(bridge, "title", "onValueChange", value="hijack", noteId=8)
    assert bridge.expose_latest_snapshot() == before
    assert bridge.expose_latest_error() != ""


def test_a_bound_literal_outside_its_values_is_refused(bridge: BridgeSurface) -> None:
    with pytest.raises(IrValidationError):
        Button(id="blue", text="Blue", on_click=Pick(value="blue"))  # type: ignore[arg-type]
    before = bridge.expose_latest_snapshot()
    bridge.accept_action(
        json.dumps(
            {
                "fields": {"value": "blue"},
                "intent": f"{Pick.__module__}.Pick",
                "payload": {},
            }
        )
    )
    assert bridge.expose_latest_snapshot() == before
    assert bridge.expose_latest_error() != ""


def test_a_nullable_field_takes_null_but_not_another_type(
    bridge: BridgeSurface,
) -> None:
    tap(bridge, "due", "onClick", value=None)
    assert shown(bridge) == "|none|None"
    tap(bridge, "due", "onClick", value="soon")
    assert shown(bridge) == "|none|None"
    assert bridge.expose_latest_error() != ""


def test_a_tap_from_a_long_gone_snapshot_still_means_what_it_meant(
    bridge: BridgeSurface,
) -> None:
    """The intent carries its own fields, so no old snapshot is needed to read it."""
    root = json.loads(bridge.expose_latest_snapshot() or "{}")["root"]
    paths = bridge.node_paths()
    red = next(c for c in root["children"] if paths[c["id"]].endswith("red"))
    for title in ("a", "b", "c"):
        tap(bridge, "title", "onValueChange", value=title)
    bridge.accept_action(json.dumps({**red["props"]["onClick"], "payload": {}}))
    assert shown(bridge) == "c|red|0"


def test_an_intent_no_app_defines_is_refused(bridge: BridgeSurface) -> None:
    before = bridge.expose_latest_snapshot()
    bridge.accept_action(
        json.dumps({"fields": {}, "intent": "nowhere.Missing", "payload": {}})
    )
    assert bridge.expose_latest_snapshot() == before
    assert bridge.expose_latest_error() != ""
