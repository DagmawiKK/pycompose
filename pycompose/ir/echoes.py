"""The report numbers a snapshot echoes back to the host's holders."""

from __future__ import annotations

from collections.abc import Mapping

from pycompose.errors import IrValidationError

__all__ = ["ECHOES_SCHEMA", "read_echoes"]

ECHOES_SCHEMA = "1.23.0"
"""First schema whose snapshots echo the host's report sequence numbers."""


def read_echoes(metadata: Mapping[str, object] | None) -> dict[str, int] | None:
    """Read the echoed report numbers out of snapshot metadata.

    Args:
        metadata: Snapshot metadata carrying an optional ``echoes`` object.

    Returns:
        The latest answered number by action id, or None when none is echoed.

    Raises:
        IrValidationError: If the section is not an object of positive integers.
    """
    raw = metadata.get("echoes") if metadata is not None else None
    if raw is None:
        return None
    if not isinstance(raw, Mapping) or not all(
        type(seq) is int and seq > 0 for seq in raw.values()
    ):
        raise IrValidationError("echoes must map action ids to positive integers")
    return {str(key): int(seq) for key, seq in raw.items()}
