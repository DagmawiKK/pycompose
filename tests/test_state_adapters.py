"""The adapter seam: how a host-owned parameter is filled at the call site.

The projection tests pin what crosses the wire; these pin how the generated
adapter asks for it. The catalog-driven families (a drawer's state, a sheet's
gate) render from the approved entries. The slider, scroll and lazy-list
shapes are stated here as the entries the catalog carries in schema 1.23.0,
so the emission is reviewed exactly once and the SSOT lands it after.
"""

from __future__ import annotations

from test_state_projection import GATED, STATEFUL, components

from pycompose.schema.codegen.adapters import extra_imports, is_mechanical, render


def test_the_adapter_passes_the_host_holder_where_the_schema_says() -> None:
    """The desired value and its report are not native parameters."""
    adapter = render(STATEFUL, components()[STATEFUL])
    assert (
        "val drawerStateValue = context.drawerState("
        "model.props.open, model.props.onOpenChange)" in adapter
    )
    assert "drawerState = drawerStateValue" in adapter
    assert "open =" not in adapter
    assert "onOpenChange =" not in adapter
    assert 'context.slot(model.children, "drawer")?.invoke()' in adapter
    assert "content = { context.children(model.children) }" in adapter


def test_a_gated_family_composes_its_component_from_the_holder() -> None:
    """A sheet shows itself once composed, so presence is the host's decision."""
    adapter = render(GATED, components()[GATED])
    assert (
        "val sheetStateValue = context.sheetState("
        "model.props.open, model.props.onOpenChange, model.props.value, "
        "model.props.onValueChange, model.props.skipPartiallyExpanded)" in adapter
    )
    assert "if (sheetStateValue.visible) {" in adapter
    assert "sheetState = sheetStateValue.state" in adapter
    # The component has already hidden itself when it calls this, and the
    # settled change reports through the report prop, so nothing answers it.
    assert "onDismissRequest = {}" in adapter
    assert "open =" not in adapter
    assert "onOpenChange =" not in adapter
    assert 'dragHandle = context.slot(model.children, "dragHandle")' in adapter
    scoped = "content = { context.childrenIn(this, model.children) }"
    assert scoped in adapter


def test_the_holder_stays_outside_the_gate() -> None:
    """The state must outlive the composition of the component it projects."""
    adapter = render(GATED, components()[GATED])
    holder = adapter.index("val sheetStateValue = context.sheetState(")
    gate = adapter.index("if (sheetStateValue.visible) {")
    assert holder < gate


def test_a_component_without_a_holder_gets_no_state_local() -> None:
    """Only components that declare a holder ask the renderer for one."""
    adapter = render("Column", components()["Column"])
    assert "context.drawerState(" not in adapter


SLIDER = {
    "props": {
        "value": {"type": "number"},
        "onValueChangeFinished": {
            "type": "actionId",
            "payload": [{"name": "value", "type": "number"}],
        },
        "valueRange": {"type": "value", "valueType": "Range", "required": True},
        "steps": {"type": "integer"},
    },
    "children": {"allowed": False},
    "state": {
        "native": "state",
        "kind": "slider",
        "value": "value",
        "report": "onValueChangeFinished",
    },
}
"""A slider entry as the catalog will carry it, before the catalog does."""

SCROLL = {
    "props": {
        "offset": {"type": "number"},
        "onScrollIdle": {"type": "actionId", "payload": []},
        "scrollable": {"type": "boolean"},
    },
    "children": {"allowed": True},
    "state": {
        "native": "scrollState",
        "kind": "scroll",
        "value": "offset",
        "report": "onScrollIdle",
    },
}
"""A scroll-gated column entry: the holder rides the modifier, not a parameter."""

LAZY = {
    "props": {
        "firstVisibleIndex": {"type": "integer"},
        "onScrollIdle": {"type": "actionId", "payload": []},
    },
    "children": {"allowed": False},
    "state": {
        "native": "state",
        "kind": "lazyList",
        "value": "firstVisibleIndex",
        "report": "onScrollIdle",
    },
}
"""A lazy-list entry: the state parameter takes the holder directly."""


def test_a_slider_carries_its_range_and_steps_to_the_holder() -> None:
    """The holder is constructed from the app's range and steps, not defaults."""
    adapter = render("Slider", SLIDER)
    # The range crosses as tagged data and reaches the holder resolved.
    assert (
        "val valueRangeValue = "
        "com.pycompose.renderer.generated.ValueResolver.range("
        "model.props.valueRange).getOrThrow()" in adapter
    )
    assert (
        "val stateValue = context.sliderState("
        "model.props.value, model.props.onValueChangeFinished, "
        "valueRangeValue, model.props.steps)" in adapter
    )
    assert "state = stateValue" in adapter
    # The held props name no native parameter: the holder consumes them.
    assert "value =" not in adapter
    assert "onValueChangeFinished =" not in adapter
    assert "valueRange =" not in adapter
    assert "steps =" not in adapter


def test_a_scroll_holder_rides_the_modifier_behind_a_boolean() -> None:
    """The scroll attaches through the modifier, gated by the app's prop."""
    adapter = render("Column", SCROLL)
    assert (
        "val scrollStateValue = context.scrollState("
        "model.props.offset, model.props.onScrollIdle)" in adapter
    )
    assert (
        "modifier = scrollStateValue.attachTo(modifier, model.props.scrollable)"
        in adapter
    )
    # The stem is documentary: Column has no state parameter to fill.
    assert "scrollState =" not in adapter
    assert "com.pycompose.renderer.attachTo" in extra_imports(SCROLL)
    assert "com.pycompose.renderer.attachTo" not in extra_imports(SLIDER)


def test_a_lazy_list_fills_the_state_parameter() -> None:
    """LazyColumn's state parameter takes the holder directly."""
    adapter = render("LazyColumn", LAZY)
    assert (
        "val stateValue = context.lazyListState("
        "model.props.firstVisibleIndex, model.props.onScrollIdle)" in adapter
    )
    assert "state = stateValue" in adapter
    assert "firstVisibleIndex =" not in adapter


def test_a_tooltip_holder_receives_persistence_after_value_and_report() -> None:
    """Every holder follows the same constructor call convention."""
    entry = {
        "props": {
            "visible": {"type": "boolean"},
            "onVisibilityChange": {"type": "actionId", "payload": []},
            "isPersistent": {"type": "boolean", "default": False},
        },
        "children": {"allowed": False},
        "state": components()["TooltipBox"]["state"],
    }
    adapter = render("Tooltip", entry)
    assert (
        "context.tooltipState(model.props.visible, model.props.onVisibilityChange, "
        "model.props.isPersistent)" in adapter
    )
    assert "isPersistent =" not in adapter
    assert "com.pycompose.renderer.tooltipState" in extra_imports(entry)


def test_a_swipe_holder_reports_the_settled_anchor_and_fills_row_slots() -> None:
    """The enum value and its report are held; both contents use RowScope."""
    entry = components()["SwipeToDismissBox"]
    adapter = render("SwipeToDismissBox", entry)
    assert (
        "val stateValue = context.swipeState("
        "model.props.value, model.props.onValueChange)" in adapter
    )
    assert "state = stateValue" in adapter
    # The holder consumes the desired anchor and its report.
    assert "value =" not in adapter
    assert "onValueChange =" not in adapter
    assert (
        "backgroundContent = context.slotIn<RowScope>("
        'model.children, "backgroundContent") ?: {}' in adapter
    )
    assert "content = { context.childrenIn(this, model.children) }" in adapter
    assert "com.pycompose.renderer.swipeState" in extra_imports(entry)


def test_a_held_enum_value_does_not_block_a_mechanical_adapter() -> None:
    """Held props never reach a native parameter, so their type is no obstacle."""
    assert is_mechanical(components()["SwipeToDismissBox"])
