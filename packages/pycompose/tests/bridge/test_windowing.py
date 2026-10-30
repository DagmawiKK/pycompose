"""A lazy container over data composes only the window the host asked for."""

from __future__ import annotations

import json

import pytest
from handlers import Handlers

from pycompose import composable
from pycompose.bridge import BridgeSurface
from pycompose.errors import IrValidationError
from pycompose.foundation import Column, LazyColumn
from pycompose.material3 import Text
from pycompose.model.nodes.windows import DEFAULT_WINDOW, MAX_WINDOW
from pycompose.state import State, Store

ROWS = list(range(10_000))


def listed() -> LazyColumn:
    return LazyColumn(
        items=ROWS, key=lambda n: f"n{n}", item=lambda n: Text(text=f"row {n}")
    )


def rows() -> State:
    return State(root=listed())


@composable
def titled(*, title: str):
    return Column(children=[Text(text=title), listed()])


BUILDS: list[str] = []


@composable
def header(*, title: str):
    BUILDS.append(title)
    return Text(text=title)


def root(bridge: BridgeSurface) -> dict[str, object]:
    return json.loads(bridge.expose_latest_snapshot() or "")["root"]


def texts(node: dict[str, object]) -> list[str]:
    return [child["props"]["text"] for child in node["children"]]  # type: ignore[index, union-attr]


def test_a_list_of_ten_thousand_composes_only_its_first_window() -> None:
    node = root(BridgeSurface(Store(rows()), Handlers()))

    assert node["props"]["itemCount"] == 10_000  # type: ignore[index]
    assert node["props"]["itemOffset"] == 0  # type: ignore[index]
    assert len(node["children"]) == DEFAULT_WINDOW  # type: ignore[arg-type]


def test_a_requested_window_is_composed_keyed_by_each_item() -> None:
    bridge = BridgeSurface(Store(rows()), Handlers())
    key = root(bridge)["props"]["window"]  # type: ignore[index]

    bridge.request_window(str(key), 5_000, 5_009)

    node = root(bridge)
    assert node["props"]["itemOffset"] == 5_000  # type: ignore[index]
    assert texts(node) == [f"row {n}" for n in range(5_000, 5_010)]
    first = node["children"][0]["id"]  # type: ignore[index]
    assert bridge.node_paths()[first].endswith("n5000")


def test_a_window_is_clamped_to_the_items_and_the_maximum() -> None:
    bridge = BridgeSurface(Store(rows()), Handlers())
    key = str(root(bridge)["props"]["window"])  # type: ignore[index]

    bridge.request_window(key, 9_995, 20_000)
    assert len(root(bridge)["children"]) == 5  # type: ignore[arg-type]
    bridge.request_window(key, 0, 9_999)
    assert len(root(bridge)["children"]) == MAX_WINDOW  # type: ignore[arg-type]


@pytest.mark.parametrize("debug", [False, True])
def test_a_list_inside_a_composable_follows_each_requested_window(
    debug: bool,
) -> None:
    bridge = BridgeSurface(
        Store(State(root=titled(id="screen", title="Rows"))), Handlers(), debug=debug
    )
    key = str(root(bridge)["children"][1]["props"]["window"])  # type: ignore[index]

    # More requests than the debug memo re-checks between, so a replayed window
    # would also surface as a reuse failure.
    for first in range(100, 1_300, 100):
        bridge.request_window(key, first, first + 9)
        node = root(bridge)["children"][1]  # type: ignore[index]
        assert node["props"]["itemOffset"] == first
        assert texts(node)[0] == f"row {first}"
    assert bridge.expose_latest_error() == ""


def test_a_composable_beside_a_windowed_list_is_still_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pycompose.bridge import api

    # As an app runs it: no re-expansion to verify reuse, which would build it.
    monkeypatch.setattr(api, "VERIFY_EVERY", 0)
    BUILDS.clear()
    state = State(root=Column(children=[header(id="header", title="Rows"), listed()]))
    bridge = BridgeSurface(Store(state), Handlers(), debug=False)
    key = str(root(bridge)["children"][1]["props"]["window"])  # type: ignore[index]

    for first in (100, 200, 300):
        bridge.request_window(key, first, first + 9)

    assert BUILDS == ["Rows"]


def test_a_windowed_list_needs_a_key() -> None:
    with pytest.raises(IrValidationError, match="needs key"):
        LazyColumn(items=ROWS, item=lambda n: Text(text=str(n)))


def test_a_short_list_may_still_be_stated_whole() -> None:
    node = LazyColumn(items=[Text(text="a"), Text(text="b")])

    assert len(node.children) == 2
