"""pycompose.host.wire — pure emitter, canonical serializer, validation tables."""

from __future__ import annotations

from pycompose.host.wire.emitter import emit_ir
from pycompose.host.wire.model import IRRoot
from pycompose.host.wire.serializer import (
    node_to_dict,
    to_dict,
    to_json,
    to_json_bytes,
)
from pycompose.host.wire.validator import ValidationResult, validate_ir

__all__ = [
    "IRRoot",
    "ValidationResult",
    "emit_ir",
    "node_to_dict",
    "to_dict",
    "to_json",
    "to_json_bytes",
    "validate_ir",
]
