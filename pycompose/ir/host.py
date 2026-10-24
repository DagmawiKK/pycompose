"""What the host can render, as its handshake said (ADR-0050).

The host lists its component types when the session starts, and the session
negotiates a wire schema. A component missing from the list, or newer than
the schema, is one the host lacks: a ``Fallback`` declaration then builds its
fallback instead, and the validator refuses one with no fallback before it is
sent.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from pycompose.ir.generated_validators import REGISTRY, SCHEMA_VERSION
from pycompose.schema.version import at_least

__all__ = ["Host", "current_host", "hosted"]


@dataclass(frozen=True, slots=True)
class Host:
    """The host a session renders on.

    Attributes:
        components: The component types it offered, or None when its offer
            listed none: every component Python knows.
        schema_version: The wire schema the session speaks.
        substituted: Types a fallback stood in for, for the session's
            diagnostic.
    """

    components: frozenset[str] | None = None
    schema_version: str = SCHEMA_VERSION
    substituted: set[str] = field(default_factory=set)

    def lacks(self, node_type: str) -> bool:
        """Report whether the host cannot render a component type.

        Args:
            node_type: A component type Python's registry knows.

        Returns:
            True when the offer omits it or the schema predates it; a type
            Python does not know is the validator's to report.
        """
        spec = REGISTRY.components.get(node_type)
        if spec is None:
            return False
        if self.components is not None and node_type not in self.components:
            return True
        return spec.since is not None and not at_least(self.schema_version, spec.since)


_host: ContextVar[Host | None] = ContextVar("host", default=None)


@contextmanager
def hosted(host: Host) -> Iterator[None]:
    """Make the session's host visible to the emission and validation inside.

    Args:
        host: The host the snapshot is for.

    Yields:
        None: While the host is visible.
    """
    token = _host.set(host)
    try:
        yield
    finally:
        _host.reset(token)


def current_host() -> Host | None:
    """Return the host of the snapshot being emitted, if any.

    Returns:
        The host, or None outside a session's emission.
    """
    return _host.get()
