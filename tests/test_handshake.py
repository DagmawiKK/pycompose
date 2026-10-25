"""The session handshake refuses a host and app that do not speak alike."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pycompose.bridge import handshake
from pycompose.bridge.runtime import handshake as runtime_handshake
from pycompose.errors import BridgeError


def offer(protocol: int = handshake.PROTOCOL, *capabilities: str) -> str:
    """Return a host handshake.

    Args:
        protocol: The host's protocol version.
        *capabilities: What the host offers.

    Returns:
        The handshake JSON.
    """
    return json.dumps({"protocol": protocol, "capabilities": list(capabilities)})


def test_a_matching_host_is_answered_with_this_sides_handshake() -> None:
    reply = json.loads(runtime_handshake(offer()))

    assert reply == {
        "capabilities": sorted(handshake.CAPABILITIES),
        "protocol": handshake.PROTOCOL,
    }


def test_a_different_protocol_is_refused_naming_both() -> None:
    with pytest.raises(BridgeError, match="protocol mismatch") as raised:
        handshake.answer(offer(handshake.PROTOCOL + 1))

    assert raised.value.context["host"] == handshake.PROTOCOL + 1


def test_a_host_lacking_a_required_capability_is_refused_naming_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(handshake, "REQUIRED", frozenset({"windows", "surfaces"}))

    with pytest.raises(BridgeError, match="lacks capabilities") as raised:
        handshake.answer(offer(handshake.PROTOCOL, "surfaces"))

    assert raised.value.context["missing"] == "windows"


@pytest.mark.parametrize("raw", ["", "[]", '{"protocol":1}', "null"])
def test_a_malformed_handshake_is_refused(raw: str) -> None:
    with pytest.raises(BridgeError, match="malformed"):
        handshake.answer(raw)


def test_the_host_and_this_side_speak_the_same_protocol() -> None:
    source = (
        Path(__file__).parents[1]
        / "android/ir/src/main/kotlin/com/pycompose/ir/Handshake.kt"
    ).read_text()
    stated = re.search(r"const val PROTOCOL = (\d+)", source)

    assert stated is not None
    assert int(stated.group(1)) == handshake.PROTOCOL
