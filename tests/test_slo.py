"""The pass-time SLO gate fails a deliberate regression and passes noise."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import slo


def test_growth_over_twenty_percent_fails_and_under_it_passes() -> None:
    before = {"passP50Ms": 1.0, "passP95Ms": 2.0}
    assert slo.regressions(before, {"passP50Ms": 1.21, "passP95Ms": 2.0}) == [
        "passP50Ms: 1.000 ms -> 1.210 ms (+21%, limit 20%)"
    ]
    assert slo.regressions(before, {"passP50Ms": 1.19, "passP95Ms": 2.39}) == []


def test_tiny_growth_is_noise_whatever_its_share() -> None:
    assert slo.regressions({"passP50Ms": 0.01}, {"passP50Ms": 0.05}) == []


def test_a_device_floor_absorbs_a_frame_of_jitter() -> None:
    before = {"tapToFrameP50Ms": 10.0}
    assert slo.regressions(before, {"tapToFrameP50Ms": 14.0}, floor_ms=5) == []
    assert slo.regressions(before, {"tapToFrameP50Ms": 16.0}, floor_ms=5) != []


def test_the_gate_fails_a_deliberate_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pycompose.bridge import api

    before = slo.measure(rounds=3, keystrokes=120)
    # Every pass waits a further quarter of today's median: past the 20% limit,
    # and measured the way CI measures it.
    delay = before["passP50Ms"] / 4 / 1000
    original = api.BridgeSurface.accept_action

    def slower(self: api.BridgeSurface, source: str) -> None:
        original(self, source)
        until = time.perf_counter() + delay
        while time.perf_counter() < until:
            pass

    monkeypatch.setattr(api.BridgeSurface, "accept_action", slower)
    after = slo.measure(rounds=3, keystrokes=120)
    assert [line.split(":")[0] for line in slo.regressions(before, after)] == [
        "passP50Ms",
        "passP95Ms",
    ]
