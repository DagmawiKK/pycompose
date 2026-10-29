"""A component the host lacks is replaced by its declared fallback (ADR-0050)."""

from __future__ import annotations

import json
import logging

import pytest
from readable import readable_reuse

from pycompose.bridge.handshake import PROTOCOL, offered_components
from pycompose.contract.catalog import REGISTRY, SCHEMA_VERSION
from pycompose.errors import BridgeError, IrValidationError
from pycompose.material3 import HorizontalDivider
from pycompose.state import State
from pycompose.ui import Column, Fallback, Text
from pycompose.wire import emit_ir, validate_ir
from pycompose.wire.host import Host, hosted

EVERYTHING = frozenset(REGISTRY.components)


def _screen() -> Column:
    return Column(
        id="screen",
        children=[Fallback(HorizontalDivider(), otherwise=Text(text="—"), id="rule")],
    )


def _types(host: Host | None, version: str = SCHEMA_VERSION) -> list[str]:
    root = emit_ir(State(root=_screen()), version).root
    if host is not None:
        with hosted(host):
            root = emit_ir(State(root=_screen()), version).root
    return [child.type for child in root.children]


def test_the_content_composes_where_the_host_renders_it() -> None:
    assert _types(None) == ["HorizontalDivider"]
    assert _types(Host(EVERYTHING)) == ["HorizontalDivider"]


def test_the_fallback_stands_in_where_the_host_lacks_the_component() -> None:
    host = Host(EVERYTHING - {"HorizontalDivider"})
    assert _types(host) == ["Text"]
    assert host.substituted == {"HorizontalDivider"}


def test_a_component_newer_than_the_hosts_schema_falls_back() -> None:
    # HorizontalDivider arrived in 1.22.0.
    assert _types(Host(None, "1.21.0"), "1.21.0") == ["Text"]


def test_the_two_sides_are_keyed_apart() -> None:
    # One session, so a shared name would mean one identity for both.
    reuse = readable_reuse()
    lacking = Host(EVERYTHING - {"HorizontalDivider"})
    shown = emit_ir(State(root=_screen()), SCHEMA_VERSION, reuse).root.children[0]
    with hosted(lacking):
        standing_in = emit_ir(
            State(root=_screen()), SCHEMA_VERSION, reuse
        ).root.children[0]
    assert shown.id != standing_in.id


def test_a_lacked_component_with_no_fallback_is_refused_before_sending() -> None:
    host = Host(EVERYTHING - {"HorizontalDivider"})
    with hosted(host):
        emitted = emit_ir(State(root=Column(children=[HorizontalDivider()])), "1.23.0")
        with pytest.raises(IrValidationError, match="give it a Fallback"):
            validate_ir(emitted)


def test_the_handshake_lists_what_the_host_renders() -> None:
    offer = {"protocol": PROTOCOL, "capabilities": []}
    assert offered_components(json.dumps(offer)) is None
    listed = json.dumps({**offer, "components": ["Text", "Column"]})
    assert offered_components(listed) == {"Text", "Column"}
    with pytest.raises(BridgeError):
        offered_components(json.dumps({**offer, "components": "Text"}))


def test_the_bridge_announces_each_substitution_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from handlers import Handlers

    from pycompose.bridge.api import BridgeSurface
    from pycompose.state import Store

    with caplog.at_level(logging.WARNING):
        surface = BridgeSurface(
            Store(State(root=_screen())),
            Handlers(),
            host_components=EVERYTHING - {"HorizontalDivider"},
        )
    snapshot = json.loads(surface.expose_latest_snapshot() or "{}")
    assert [c["type"] for c in snapshot["root"]["children"]] == ["Text"]
    assert (
        caplog.messages.count("The host has no HorizontalDivider; showing its fallback")
        == 1
    )


def test_the_runtime_keeps_the_hosts_list_for_the_sessions_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pycompose.bridge import runtime, session

    monkeypatch.setattr(session, "_host_components", None)
    offer = {"protocol": PROTOCOL, "capabilities": [], "components": ["Text"]}
    runtime.handshake(json.dumps(offer))
    assert session._host_components == {"Text"}
