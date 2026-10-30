"""Immutable one-shot effect requests; Python names the intent, the host acts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pycompose.errors import IrValidationError
from pycompose.model.canonical import FrozenJsonValue, freeze_json, thaw_json
from pycompose.model.nodes.props import JsonValue

__all__ = ["Effect"]

_KIND = re.compile(r"[A-Za-z][A-Za-z0-9]*")


@dataclass(frozen=True, slots=True)
class Effect:
    """One request for the host to execute exactly once, in order.

    An effect is data, not state: it describes something the app wants the host
    to do, and the host drops it after acting. Anything that must survive a
    configuration change belongs in State instead.

    Attributes:
        kind: Registered effect kind, such as ``navigate``.
        payload: Frozen JSON values keyed by wire field name.
    """

    kind: str
    payload: Mapping[str, FrozenJsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Freeze the payload and reject a malformed kind.

        Raises:
            IrValidationError: If the kind or payload is not usable data.
        """
        if not isinstance(self.kind, str) or _KIND.fullmatch(self.kind) is None:
            raise IrValidationError("invalid effect kind", kind=str(self.kind))
        if not isinstance(self.payload, Mapping):
            raise IrValidationError("effect payload must be a mapping")
        frozen = freeze_json(self.payload)
        if not isinstance(frozen, Mapping):
            raise IrValidationError("effect payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(frozen)))

    def to_wire(self) -> dict[str, JsonValue]:
        """Return the JSON-ready envelope member for this request.

        Returns:
            An object with ``kind`` and ``payload``, detached from this value.
        """
        return {"kind": self.kind, "payload": thaw_json(dict(self.payload))}
