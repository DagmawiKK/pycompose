"""The versioned snapshot exchanged with the host."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pycompose.core.node import Node
from pycompose.core.props import JsonValue
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json
from pycompose.version import __version__

__all__ = ["IRRoot"]


@dataclass(frozen=True, slots=True)
class IRRoot:
    """A full IR snapshot, distinct from an application's State counter.

    Attributes:
        root: Root node of the emitted IR.
        schema_version: Version of the wire contract.
        version: Library version, not a rebuild sequence number.
        metadata: Optional explicit JSON data; never implicit time or environment.
    """

    root: Node
    schema_version: str
    version: str = __version__
    metadata: Mapping[str, JsonValue | FrozenJsonValue] | None = None

    def __post_init__(self) -> None:
        if self.metadata is not None:
            object.__setattr__(self, "metadata", freeze_json(self.metadata))
