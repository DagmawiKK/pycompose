"""The report numbers a snapshot echoes back to the host's holders."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from pycompose.core.props import JsonValue
from pycompose.errors import IrValidationError
from pycompose.utils.json_canonical import canonical_json

__all__ = ["ECHOES_SCHEMA", "echo_key", "lower_echoes", "read_echoes"]

ECHOES_SCHEMA = "1.23.0"
"""First schema whose snapshots echo the host's report sequence numbers."""


def echo_key(target: object) -> str:
    """Return the key an echo is kept under: its target's canonical JSON.

    Args:
        target: The intent a report was sent to, or a registry action's name.

    Returns:
        A key equal for equal targets.
    """
    return canonical_json(target)


def lower_echoes(echoes: Mapping[str, int]) -> list[JsonValue]:
    """Return the echoes as the wire states them, in key order.

    Args:
        echoes: The latest answered number by echo key.

    Returns:
        ``{"seq": ..., "target": ...}`` objects; the target is the intent the
        report named, exactly as its control carries it.
    """
    return [
        {"seq": seq, "target": json.loads(key)} for key, seq in sorted(echoes.items())
    ]


def read_echoes(metadata: Mapping[str, object] | None) -> dict[str, int] | None:
    """Read the echoed report numbers out of snapshot metadata.

    Args:
        metadata: Snapshot metadata carrying an optional ``echoes`` list.

    Returns:
        The latest answered number by echo key, or None when none is echoed.

    Raises:
        IrValidationError: If the section is not a list of targets and numbers.
    """
    raw = metadata.get("echoes") if metadata is not None else None
    if raw is None:
        return None
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise IrValidationError("echoes must be a list")
    result: dict[str, int] = {}
    for entry in raw:
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"seq", "target"}
            or type(entry["seq"]) is not int
            or entry["seq"] < 1
            or not isinstance(entry["target"], str | Mapping)
        ):
            raise IrValidationError("echoes must pair targets with positive integers")
        result[echo_key(entry["target"])] = entry["seq"]
    return result
