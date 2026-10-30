"""Release-safe pass statistics and span export for one bridge surface."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from pycompose.app.observe import Span

__all__ = ["PassStats"]

LOGGER = logging.getLogger(__name__)


class PassStats:
    """Counts passes, publications and failures, and exports one span per pass.

    Args:
        on_pass: Receives each pass's span; None exports nothing.
    """

    def __init__(self, on_pass: Callable[[Span], None] | None = None) -> None:
        self._on_pass = on_pass
        self.counts = {"passes": 0, "published": 0, "failedActions": 0}
        self._phase_ms: dict[str, float] = {}
        self._max_pass_ms = 0.0

    def record(
        self,
        name: str,
        trace: str | None,
        spent: float,
        phases: Mapping[str, float],
        *,
        failed: bool,
    ) -> None:
        """Count one pass and hand its span to the exporter.

        Args:
            name: The intent or event the pass handled.
            trace: The input's trace id, or None.
            spent: The pass's milliseconds.
            phases: Its milliseconds by phase.
            failed: Whether it ended in an error.
        """
        self.counts["passes"] += 1
        self.counts["failedActions"] += failed
        self._max_pass_ms = max(self._max_pass_ms, spent)
        for phase, ms in phases.items():
            self._phase_ms[phase] = self._phase_ms.get(phase, 0.0) + ms
        if self._on_pass is not None:
            try:
                self._on_pass(Span(trace, name, spent, dict(phases), failed))
            except Exception:  # an exporter never breaks a pass
                LOGGER.exception("The span exporter failed")

    def snapshot(self) -> dict[str, object]:
        """Return the counts, the longest pass and total milliseconds by phase.

        Returns:
            Release-safe counters as plain data.
        """
        return {
            **self.counts,
            "maxPassMs": round(self._max_pass_ms, 3),
            "phaseMs": {k: round(v, 3) for k, v in sorted(self._phase_ms.items())},
        }
