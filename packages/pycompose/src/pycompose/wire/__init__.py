"""pycompose.wire — pure emitter, canonical serializer, validation tables."""

from __future__ import annotations

from pycompose.wire.emitter import emit_ir
from pycompose.wire.model import IRRoot
from pycompose.wire.serializer import (
    node_to_dict,
    to_dict,
    to_json,
    to_json_bytes,
)
from pycompose.wire.validator import ValidationResult, validate_ir

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
