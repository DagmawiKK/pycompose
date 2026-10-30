"""Release observability: failures reach on_error with their trace, passes export."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from pycompose.host.bridge import runtime

APP = """
import asyncio
from pycompose.app import App, Destination, Intent, ViewModel
from pycompose.ui import Column
from pycompose.ui import Button, Text
from pycompose.state import AppState

FAILURES = []
SPANS = []
BROKEN_HOOK = []


class Screen(AppState):
    count: int = 0


class Work(Intent):
    pass


class Crash(Intent):
    pass


class Bump(Intent):
    pass


class ScreenViewModel(ViewModel[Screen]):
    def __init__(self):
        super().__init__(Screen())

    def on_intent(self, intent):
        if isinstance(intent, Work):
            self.launch(self.work())
        elif isinstance(intent, Crash):
            raise RuntimeError("handler broke")
        else:
            self.state = self.state.evolve(count=self.state.count + 1)

    async def work(self):
        await asyncio.sleep(0)
        raise ValueError("background broke")


def on_error(failure):
    FAILURES.append(failure)
    if BROKEN_HOOK:
        raise RuntimeError("the hook itself broke")


def screen(state):
    return Column(children=[
        Text(id="count", text=str(state.count)),
        Button(id="work", text="work", on_click=Work()),
        Button(id="crash", text="crash", on_click=Crash()),
        Button(id="bump", text="bump", on_click=Bump()),
    ])


app = App(
    start=Destination(lambda _c, _r: ScreenViewModel(), screen),
    on_error=on_error,
    exporter=SPANS.append,
)
"""


@pytest.fixture
def observed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    (tmp_path / "observed_app.py").write_text(APP)
    monkeypatch.syspath_prepend(str(tmp_path))
    runtime.start("observed_app:app", "", False)
    yield sys.modules["observed_app"]
    runtime.close()
    sys.modules.pop("observed_app", None)


def tap(node: int, trace: str) -> None:
    root = json.loads(runtime.fetch_latest_snapshot())["root"]
    intent = root["children"][node]["props"]["onClick"]
    runtime.accept_action(json.dumps({**intent, "payload": {}, "trace": trace}))


def settle() -> None:
    for _ in range(3):
        runtime._loop_thread().call(lambda: None)


def test_failed_work_reaches_on_error_with_the_trace_that_launched_it(
    observed: object,
) -> None:
    tap(1, "trace-work")
    settle()
    (failure,) = observed.FAILURES  # type: ignore[attr-defined]
    assert failure.scope == "ScreenViewModel"
    assert isinstance(failure.error, ValueError)
    assert failure.trace == "trace-work"


def test_a_failing_handler_reaches_on_error_with_its_trace(observed: object) -> None:
    tap(2, "trace-crash")
    (failure,) = observed.FAILURES  # type: ignore[attr-defined]
    assert failure.scope.endswith("Crash")
    assert str(failure.error) == "handler broke"
    assert failure.trace == "trace-crash"
    assert "handler broke" in runtime.fetch_latest_error()


def test_a_failing_hook_breaks_nothing(observed: object) -> None:
    observed.BROKEN_HOOK.append(True)  # type: ignore[attr-defined]
    tap(2, "trace-crash")
    tap(3, "trace-bump")
    root = json.loads(runtime.fetch_latest_snapshot())["root"]
    assert root["children"][0]["props"]["text"] == "1"


def test_every_pass_exports_a_span(observed: object) -> None:
    tap(3, "trace-bump")
    tap(2, "trace-crash")
    spans = observed.SPANS  # type: ignore[attr-defined]
    assert [(s.trace, s.name.rpartition(".")[2], s.failed) for s in spans] == [
        ("trace-bump", "Bump", False),
        ("trace-crash", "Crash", True),
    ]
    # An action's span is its handler; drawing happens once, at the pull.
    assert set(spans[0].phases) == {"handler"}
