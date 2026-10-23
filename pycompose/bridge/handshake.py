"""The session handshake: what each side of the bridge speaks (plan 31 §16.8).

The host and the Python app may come from different builds, so before a session
starts each states its protocol version and the capabilities it offers, and each
checks the other offers what it requires. A mismatch fails at startup naming
what is missing, instead of misrendering later. New wire shapes arrive as
capabilities, so each grows without a flag day.
"""

from __future__ import annotations

import json

from pycompose.errors import BridgeError

__all__ = ["CAPABILITIES", "PROTOCOL", "REQUIRED", "answer"]

PROTOCOL = 1
"""Bumped only by a change no capability can describe."""

CAPABILITIES: frozenset[str] = frozenset()
"""What this side offers the host."""

REQUIRED: frozenset[str] = frozenset()
"""What this side needs the host to offer."""


def answer(offer: str) -> str:
    """Check the host's handshake and answer with this side's.

    Args:
        offer: The host's handshake: its protocol and the capabilities it offers.

    Returns:
        This side's handshake, as JSON.

    Raises:
        BridgeError: If the protocols differ or the host lacks a required
            capability.
    """
    try:
        host = json.loads(offer)
        protocol = host["protocol"]
        offered = set(host["capabilities"])
    except (TypeError, ValueError, KeyError) as exc:
        raise BridgeError("malformed host handshake") from exc
    if protocol != PROTOCOL:
        raise BridgeError("bridge protocol mismatch", host=protocol, app=PROTOCOL)
    missing = REQUIRED - offered
    if missing:
        raise BridgeError("host lacks capabilities", missing=",".join(sorted(missing)))
    return json.dumps(
        {"capabilities": sorted(CAPABILITIES), "protocol": PROTOCOL},
        separators=(",", ":"),
    )
