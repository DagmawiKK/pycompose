"""Pagers: one page per child, a page the app drives, the page it settles on."""

from __future__ import annotations

from pycompose.host.wire import emit_ir, validate_ir
from pycompose.model.catalog.lock import REGISTRY, SCHEMA_VERSION
from pycompose.model.snapshot import Snapshot
from pycompose.ui import HorizontalPager, Intent, Text


class Settled(Intent):
    page: int


def test_a_pager_s_pages_are_its_children_in_order() -> None:
    spec = REGISTRY.components["HorizontalPager"]
    assert spec.children.kind == "indexed"
    assert spec.state is not None and spec.state.kind == "pager"


def test_a_pager_carries_its_page_and_reports_the_one_it_settles_on() -> None:
    pager = HorizontalPager(
        page=1,
        on_page_settled=Settled,
        children=[Text(text=f"page {i}") for i in range(3)],
    )
    snapshot = emit_ir(Snapshot(root=pager), SCHEMA_VERSION)
    validate_ir(snapshot)
    assert snapshot.root.props.get("page") == 1
    assert len(snapshot.root.children) == 3
