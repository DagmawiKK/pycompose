"""Host lifecycle events: delivery shape, contract gating and the bare-name alias."""

from __future__ import annotations

import json
from typing import TypedDict

import pytest

from pycompose import action
from pycompose.bridge import BridgeSurface
from pycompose.errors import IrValidationError
from pycompose.ir import emit_ir
from pycompose.m3 import Button, Text
from pycompose.state import Actions, State, Store

seen: list[str] = []


class Empty(TypedDict):
    pass


class ConfigPayload(TypedDict):
    orientation: str
    dark_mode: bool
    locale: str
    density: float


@action
def on_resume(state: State, payload: Empty) -> State:  # noqa: ARG001
    """A resumed app decides for itself whether anything needs reloading."""
    seen.append("resume")
    return replace_root(state, "resumed")


@action
def on_config_changed(state: State, payload: ConfigPayload) -> State:
    """Only UI-affecting facts belong here; the host sends what Python cannot see."""
    seen.append(f"{payload['orientation']}/{payload['locale']}/{payload['density']}")
    return replace_root(state, payload["locale"])


def replace_root(state: State, text: str) -> State:
    return State(root=Text(id="text", text=text), version=state.version + 1)


def test_app_actions_are_addressable_by_qualified_and_bare_names() -> None:
    registry = Actions(on_resume, on_config_changed)
    handlers = registry.handlers()
    assert on_resume.name in handlers
    assert on_config_changed.name in handlers
    assert "onResume" in handlers
    assert "onConfigChanged" in handlers
    # The alias never displaces an existing registration.
    assert handlers["onResume"] is handlers[on_resume.name]
    assert handlers["onConfigChanged"] is handlers[on_config_changed.name]


def test_lifecycle_events_reach_python_through_the_ordinary_action_queue() -> None:
    store = Store(State(root=Text(id="text", text="home")))
    bridge = BridgeSurface(store, Actions(on_resume, on_config_changed))
    seen.clear()

    bridge.accept_action(json.dumps({"actionId": "onResume", "payload": {}}))
    assert json.loads(bridge.expose_latest_snapshot() or "{}")["root"]["props"][
        "text"
    ] == ("resumed")

    bridge.accept_action(
        json.dumps(
            {
                "actionId": "onConfigChanged",
                "payload": {
                    "orientation": "landscape",
                    "darkMode": True,
                    "locale": "fr-FR",
                    "density": 3.0,
                },
            }
        )
    )
    assert json.loads(bridge.expose_latest_snapshot() or "{}")["root"]["props"][
        "text"
    ] == ("fr-FR")
    assert seen == ["resume", "landscape/fr-FR/3.0"]
    assert bridge.expose_latest_error() == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"orientation": "landscape"},
        {"orientation": "landscape", "darkMode": True, "locale": "fr-FR"},
        {
            "orientation": "sideways",
            "darkMode": True,
            "locale": "fr-FR",
            "density": 3.0,
        },
        {
            "orientation": "landscape",
            "darkMode": "yes",
            "locale": "fr-FR",
            "density": 3.0,
        },
    ],
)
def test_an_ill_formed_lifecycle_payload_leaves_state_untouched(
    payload: dict[str, object],
) -> None:
    state = State(root=Text(id="text", text="home"))
    bridge = BridgeSurface(Store(state), Actions(on_config_changed))
    before = bridge.expose_latest_snapshot()
    bridge.accept_action(
        json.dumps({"actionId": "onConfigChanged", "payload": payload})
    )
    assert bridge.expose_latest_snapshot() == before
    assert bridge.expose_latest_error()


def test_handlers_receive_python_names_never_the_wire_spelling() -> None:
    assert on_config_changed.aliases == {
        "orientation": "orientation",
        "darkMode": "dark_mode",
        "locale": "locale",
        "density": "density",
    }
    seen.clear()
    store = Store(State(root=Text(id="text", text="home")))
    bridge = BridgeSurface(store, Actions(on_config_changed))
    bridge.accept_action(
        json.dumps(
            {
                "actionId": "onConfigChanged",
                "payload": {
                    "orientation": "portrait",
                    "darkMode": False,
                    "locale": "en-GB",
                    "density": 2.0,
                },
            }
        )
    )
    # The handler read payload["locale"], never the camelCase wire spelling.
    assert seen == ["portrait/en-GB/2.0"]


def test_lifecycle_is_not_a_ui_action_so_components_cannot_bind_it() -> None:
    with pytest.raises(IrValidationError, match="invalid prop"):
        Button(id="x", text="Go", on_click="onResume")
    assert emit_ir(State(root=Text(id="t", text="ok")), "1.4.0").metadata is None
