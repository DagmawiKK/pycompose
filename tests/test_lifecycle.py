"""Host lifecycle events at the bridge: delivery, contract gating, idleness."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping

import pytest
from handlers import Handlers

from pycompose.bridge import BridgeSurface
from pycompose.errors import IrValidationError
from pycompose.ir import emit_ir
from pycompose.m3 import Button, Text
from pycompose.state import State, Store

CONFIG = {
    "orientation": "landscape",
    "darkMode": True,
    "locale": "fr-FR",
    "density": 3.0,
}


def shows(text: str) -> State:
    return State(root=Text(id="text", text=text))


def handling(name: str, seen: list[Mapping[str, object]]) -> Handlers:
    handlers = Handlers()

    def handle(_state: State, payload: Mapping[str, object]) -> State:
        seen.append(payload)
        return shows(name)

    handlers.register(name, handle)
    return handlers


def text(bridge: BridgeSurface) -> str:
    return json.loads(bridge.expose_latest_snapshot() or "{}")["root"]["props"]["text"]


def test_lifecycle_events_reach_python_through_the_ordinary_action_queue() -> None:
    seen: list[Mapping[str, object]] = []
    bridge = BridgeSurface(Store(shows("home")), handling("onConfigChanged", seen))

    bridge.accept_action(json.dumps({"intent": "onConfigChanged", "payload": CONFIG}))

    assert text(bridge) == "onConfigChanged"
    assert seen == [CONFIG]
    assert bridge.expose_latest_error() == ""


def test_an_unhandled_lifecycle_event_is_idle_not_a_diagnostic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The host sends every lifecycle fact; ignoring one is the app's choice."""
    bridge = BridgeSurface(Store(shows("home")), handling("onResume", []))
    before = bridge.expose_latest_snapshot()

    with caplog.at_level(logging.DEBUG):
        bridge.accept_action(
            json.dumps({"intent": "onConfigChanged", "payload": CONFIG})
        )

    assert bridge.expose_latest_snapshot() == before
    assert bridge.expose_latest_error() == ""
    assert [r.levelno for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_an_unhandled_catalog_action_is_still_a_diagnostic() -> None:
    """A control wired to an action nobody handles remains a wiring fault."""
    bridge = BridgeSurface(Store(shows("home")), Handlers())

    bridge.accept_action('{"intent":"increment","payload":{"by":1}}')

    assert "unknown action" in bridge.expose_latest_error()


@pytest.mark.parametrize(
    "payload",
    [
        {"orientation": "landscape"},
        {"orientation": "landscape", "darkMode": True, "locale": "fr-FR"},
        {**CONFIG, "orientation": "sideways"},
        {**CONFIG, "darkMode": "yes"},
    ],
)
def test_an_ill_formed_lifecycle_payload_leaves_state_untouched(
    payload: dict[str, object],
) -> None:
    seen: list[Mapping[str, object]] = []
    bridge = BridgeSurface(Store(shows("home")), handling("onConfigChanged", seen))
    before = bridge.expose_latest_snapshot()

    bridge.accept_action(json.dumps({"intent": "onConfigChanged", "payload": payload}))

    assert bridge.expose_latest_snapshot() == before
    assert bridge.expose_latest_error()
    assert seen == []


def test_lifecycle_is_not_a_ui_action_so_components_cannot_bind_it() -> None:
    with pytest.raises(IrValidationError, match="invalid prop"):
        Button(id="x", text="Go", on_click="onResume")
    assert emit_ir(shows("ok"), "1.4.0").metadata is None
