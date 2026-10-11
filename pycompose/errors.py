"""PyCompose error hierarchy.

All PyCompose failures derive from :class:`PyComposeError` so callers can catch
a single base type; each domain ships a narrow subclass with the context needed
to fail fast and degrade safely (see ADR-0005).
"""

from __future__ import annotations

__all__ = [
    "BridgeError",
    "ComponentRegistryError",
    "IrDecodeError",
    "IrError",
    "IrValidationError",
    "PyComposeError",
    "SchemaError",
    "StateError",
]


class PyComposeError(Exception):
    """Base class for every PyCompose error."""


class SchemaError(PyComposeError):
    """The registry/schema definition is invalid or out of date."""


class IrError(PyComposeError):
    """IR construction, validation, or decoding failed."""


class IrValidationError(IrError):
    """IR failed validation against the registry tables."""


class IrDecodeError(IrError):
    """A canonical IR snapshot could not be decoded."""


class StateError(PyComposeError):
    """Invalid State or Store usage."""


class BridgeError(PyComposeError):
    """The Python bridge surface contract was violated."""


class ComponentRegistryError(PyComposeError):
    """A component is missing from or misregistered in the registry."""
