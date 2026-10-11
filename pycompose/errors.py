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
    """Base class for every PyCompose error.

    Accepts optional keyword ``context`` (e.g. ``node_id``, ``node_type``,
    ``path``) appended to the message, so a failure names the exact node or
    registry entry it came from.
    """

    def __init__(self, message: str = "", **context: object) -> None:
        """Create the error.

        Args:
            message: Human-readable summary.
            **context: Structured details appended to the message.
        """
        self.context: dict[str, object] = dict(context)
        super().__init__(message)

    def __str__(self) -> str:
        """Render the message with sorted context details appended.

        Returns:
            The message, plus ``key=value`` details when context is present.
        """
        message = super().__str__()
        if not self.context:
            return message
        details = ", ".join(
            f"{key}={value!r}" for key, value in sorted(self.context.items())
        )
        return f"{message} ({details})" if message else details


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
