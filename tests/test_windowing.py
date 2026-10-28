"""A lazy container over data composes only the window the host asked for."""

from __future__ import annotations

import json

import pytest
from handlers import Handlers

from pycompose.bridge import BridgeSurface
from pycompose.core.windows import DEFAULT_WINDOW, MAX_WINDOW
from pycompose.errors import IrValidationError
from pycompose.m3 import LazyColumn, Text
from pycompose.state import State, Store

ROWS = list(range(10_000))


def rows() -> State:
    return State(
        root=LazyColumn(
            items=ROWS, key=lambda n: f"n{n}", item=lambda n: Text(text=f"row {n}")
        )
    )


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


def test_a_windowed_list_needs_a_key() -> None:
    with pytest.raises(IrValidationError, match="needs key"):
        LazyColumn(items=ROWS, item=lambda n: Text(text=str(n)))


def test_a_short_list_may_still_be_stated_whole() -> None:
    node = LazyColumn(items=[Text(text="a"), Text(text="b")])

    assert len(node.children) == 2
