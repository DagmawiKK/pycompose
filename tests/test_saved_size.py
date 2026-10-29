"""Saved state fits Android's transaction: debug refuses a screen that outgrows it."""

from __future__ import annotations

import json

from pycompose.app import App, Destination, Intent, ViewModel
from pycompose.app.session import SAVED_LIMIT, NavigationSession
from pycompose.bridge import BridgeSurface
from pycompose.m3 import Button, Column, Text
from pycompose.state import AppState, Loaded, Store


class Draft(AppState):
    body: str = ""
    rows: Loaded[tuple[str, ...]] = ()


class Grow(Intent):
    size: int


class Load(Intent):
    pass


class DraftViewModel(ViewModel[Draft]):
    def __init__(self) -> None:
        super().__init__(Draft())

    def on_intent(self, intent: Intent) -> None:
        if isinstance(intent, Grow):
            self.state = self.state.evolve(body="x" * intent.size)
        elif isinstance(intent, Load):
            self.state = self.state.evolve(rows=("y" * 1000,) * 100)


def screen(state: Draft) -> Column:
    return Column(
        id="screen",
        children=[
            Text(id="size", text=str(len(state.body) + len(state.rows))),
            Button(id="big", text="Big", on_click=Grow(size=SAVED_LIMIT + 1)),
            Button(id="small", text="Small", on_click=Grow(size=10)),
            Button(id="load", text="Load", on_click=Load()),
        ],
    )


APP = App(start=Destination(lambda _c, _r: DraftViewModel(), screen))


def bridge(*, debug: bool) -> BridgeSurface:
    session = NavigationSession(
        APP, None, "", "", report=lambda *_: None, signal=lambda: None, debug=debug
    )
    return BridgeSurface(Store(session.snapshot_state(None)), session, debug=debug)


def tap(surface: BridgeSurface, node: int) -> str:
    root = json.loads(surface.expose_latest_snapshot() or "{}")["root"]
    intent = root["children"][node]["props"]["onClick"]
    surface.accept_action(json.dumps({**intent, "payload": {}}))
    return str(
        json.loads(surface.expose_latest_snapshot() or "{}")["root"]["children"][0][
            "props"
        ]["text"]
    )


def test_debug_refuses_saved_state_past_the_limit_and_names_the_screen() -> None:
    surface = bridge(debug=True)
    assert tap(surface, 2) == "10"
    assert tap(surface, 1) == "10"  # the last good snapshot stays
    assert "too large" in surface.expose_latest_error()
    assert "Home" in surface.expose_latest_error()


def test_loaded_fields_never_count_against_the_limit() -> None:
    surface = bridge(debug=True)
    assert tap(surface, 3) == "100"
    assert surface.expose_latest_error() == ""


def test_release_does_not_measure() -> None:
    surface = bridge(debug=False)
    assert tap(surface, 1) == str(SAVED_LIMIT + 1)
