"""Item components are applied to a builder's receiver; handed holders reconcile."""

from __future__ import annotations

import json
from typing import Any

from pycompose_codegen.emit.adapters.assemble import render
from pycompose_codegen.emit.adapters.items import item_refusal
from pycompose_codegen.emit.rules import SCHEMA_PATH


def _entry(name: str) -> dict[str, Any]:
    entry: dict[str, Any] = json.loads(SCHEMA_PATH.read_text())["components"][name]
    return entry


def test_a_builder_applies_its_children_to_its_receiver() -> None:
    block = render("AppBarRow", _entry("AppBarRow"))
    assert "content = { context.applyItems(this, model.children.unslotted()) }" in block


def test_a_handed_holder_is_driven_by_the_member_setting_each_value() -> None:
    block = render("AppBarRow", _entry("AppBarRow"))
    assert "overflowIndicator = { holder ->" in block
    assert (
        "model.props.isExpanded?.let(::Wanted), model.props.onIsExpandedChange" in block
    )
    assert "{ if (it) holder.show() else holder.dismiss() }" in block
    assert 'context.slot(model.children, "overflowIndicator")?.invoke()' in block


def test_an_item_registers_for_its_scope_and_wears_no_modifier() -> None:
    block = render("AppBarClickableItem", _entry("AppBarClickableItem"))
    head = '.registerItem<AppBarScope>("AppBarClickableItem") { node, context ->'
    assert block.lstrip().startswith(head)
    assert "clickableItem(" in block
    assert "modifier" not in block


def test_an_item_needing_composition_is_refused_with_what_it_needs() -> None:
    entry = _entry("AppBarClickableItem")
    entry["interaction"] = {"native": "interactionSource", "observations": {}}
    assert item_refusal(entry) == (
        "an item is applied outside composition, where interaction cannot be"
    )
    assert render("AppBarClickableItem", entry) == ""
