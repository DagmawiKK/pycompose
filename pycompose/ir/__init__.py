"""pycompose.ir — pure emitter, canonical serializer, validation tables."""

from __future__ import annotations

from pycompose.ir.actions import Action, ActionQueue
from pycompose.ir.emitter import emit_ir
from pycompose.ir.model import IRRoot
from pycompose.ir.serializer import (
    node_to_dict,
    to_dict,
    to_json,
    to_json_bytes,
)
from pycompose.ir.validator import ValidationIssue, ValidationResult, validate_ir

__all__ = [
    "Action",
    "ActionQueue",
    "IRRoot",
    "ValidationIssue",
    "ValidationResult",
    "emit_ir",
    "node_to_dict",
    "to_dict",
    "to_json",
    "to_json_bytes",
    "validate_ir",
]
