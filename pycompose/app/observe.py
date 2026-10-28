"""What an app can observe about itself in release: failures and passes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["Failure", "Span"]


@dataclass(frozen=True)
class Failure:
    """A supervised failure, as ``App.on_error`` receives it.

    Attributes:
        scope: What failed: a view model's work, or an intent's handler.
        error: The exception.
        trace: The trace id of the host input that led to it, or None.
    """

    scope: str
    error: BaseException
    trace: str | None


@dataclass(frozen=True)
class Span:
    """One pass, as ``App.exporter`` receives it; shaped like an OpenTelemetry span.

    Attributes:
        trace: The trace id of the host input, or None.
        name: The intent or event the pass handled.
        duration_ms: How long the pass took.
        phases: Milliseconds by phase: handler, view, validate, serialize.
        failed: Whether the pass ended in an error.
    """

    trace: str | None
    name: str
    duration_ms: float
    phases: Mapping[str, float]
    failed: bool
