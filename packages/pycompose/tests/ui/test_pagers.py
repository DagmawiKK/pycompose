"""Pagers and carousels: one page per child, driven by the app, reported settled."""

from __future__ import annotations

from pycompose.host.wire import emit_ir, validate_ir
from pycompose.model.catalog.lock import REGISTRY, SCHEMA_VERSION
from pycompose.model.snapshot import Snapshot
from pycompose.ui import HorizontalMultiBrowseCarousel, HorizontalPager, Intent, Text


class Settled(Intent):
    position: int


def test_a_pager_s_pages_are_its_children_in_order() -> None:
    spec = REGISTRY.components["HorizontalPager"]
    assert spec.children.kind == "indexed"
    assert spec.state is not None and spec.state.kind == "positional"


def test_a_pager_carries_its_page_and_reports_the_one_it_settles_on() -> None:
    pager = HorizontalPager(
        current_page=1,
        on_current_page_settled=Settled,
        children=[Text(text=f"page {i}") for i in range(3)],
    )
    snapshot = emit_ir(Snapshot(root=pager), SCHEMA_VERSION)
    validate_ir(snapshot)
    assert snapshot.root.props.get("currentPage") == 1
    assert len(snapshot.root.children) == 3


def test_a_carousel_s_items_are_its_children_and_it_reports_the_settled_item() -> None:
    spec = REGISTRY.components["HorizontalMultiBrowseCarousel"]
    assert spec.state is not None and spec.state.kind == "positional"
    carousel = HorizontalMultiBrowseCarousel(
        preferred_item_width=120,
        current_item=2,
        on_current_item_settled=Settled,
        children=[Text(text=f"item {i}") for i in range(4)],
    )
    validate_ir(emit_ir(Snapshot(root=carousel), SCHEMA_VERSION))


def test_a_pager_travels_to_a_bound_page_and_a_list_without_a_spec_refuses() -> None:
    from pycompose.errors import IrValidationError
    from pycompose.model.canonical import thaw_json
    from pycompose.ui import LazyColumn, animate, tween

    pager = HorizontalPager(
        current_page=animate(2, tween(600)),
        children=[Text(text=f"Page {i}") for i in range(3)],
    )
    snapshot = emit_ir(Snapshot(root=pager), SCHEMA_VERSION)
    assert validate_ir(snapshot).snapshot is snapshot
    assert thaw_json(snapshot.root.props.get("currentPage")) == {
        "type": "binding",
        "target": 2,
        "travel": {"kind": "tween", "durationMs": 600, "delayMs": 0},
        "phase": "composition",
    }
    # Its animated drive takes no spec, so the list's position stays plain.
    try:
        LazyColumn(first_visible_item_index=animate(5, tween()), children=[])
    except IrValidationError:
        pass
    else:
        raise AssertionError("a list position without a spec took a binding")
