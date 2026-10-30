"""Carry app-owned State data in snapshot metadata so the host can rehydrate it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pycompose.errors import IrValidationError
from pycompose.model.canonical import FrozenJsonValue, freeze_json, thaw_json
from pycompose.model.nodes.props import JsonValue

__all__ = ["DATA_SCHEMA", "lower_data", "read_data"]

# App data in the envelope arrived with this schema; earlier hosts reject it.
DATA_SCHEMA = "1.4.0"


def lower_data(
    data: Mapping[str, JsonValue | FrozenJsonValue] | None,
) -> Mapping[str, FrozenJsonValue] | None:
    """Build the wire metadata member carrying app data.

    The State froze its data once, on construction; the frozen value is carried
    as it is, and the snapshot reuses it rather than copying it again.

    Args:
        data: Frozen app data from the State being emitted.

    Returns:
        Metadata to merge into the snapshot, or None when the app holds none.
    """
    if data is None:
        return None
    frozen = freeze_json(data)
    if not isinstance(frozen, Mapping):
        return None
    return {"data": frozen}


def read_data(metadata: Mapping[str, object] | None) -> dict[str, JsonValue] | None:
    """Read app data back out of snapshot metadata.

    Args:
        metadata: Snapshot metadata carrying an optional ``data`` object.

    Returns:
        A detached copy of the app data, or None when the app published none.

    Raises:
        IrValidationError: If the value is present but is not an object.
    """
    raw = metadata.get("data") if metadata is not None else None
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise IrValidationError("snapshot data must be an object")
    return cast("dict[str, JsonValue]", thaw_json(dict(raw)))
