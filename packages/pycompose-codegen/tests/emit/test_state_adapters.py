"""The adapter seam: how a host-owned parameter is filled at the call site.

The projection tests pin what crosses the wire; these pin how the generated
adapter asks for it. The catalog-driven families (a drawer's state, a sheet's
gate) render from the approved entries. The slider, scroll and lazy-list
shapes are stated here as the entries the catalog carries in schema 1.23.0,
so the emission is reviewed exactly once and the SSOT lands it after.
"""

from __future__ import annotations

from pycompose_codegen.emit.adapters.assemble import render
from pycompose_codegen.emit.adapters.eligibility import is_mechanical
from pycompose_codegen.emit.adapters.imports import extra_imports
from test_state_projection import GATED, components


def test_the_adapter_passes_the_host_holder_where_the_schema_says() -> None:
    """The desired value and its report are not native parameters."""
    drawer = "ModalNavigationDrawer"
    adapter = render(drawer, components()[drawer])
    assert "val drawerStateValue = context.anchoredState(" in adapter
    assert "model.props.value, model.props.onValueChange," in adapter
    assert "drawerState = drawerStateValue" in adapter
    assert "value =" not in adapter
    assert "onValueChange =" not in adapter
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
    assert "context.anchoredState(" not in adapter


SCROLL = {
    "props": {
        "value": {"type": "integer"},
        "onValueSettled": {"type": "actionId", "payload": []},
        "scrollable": {"type": "boolean"},
    },
    "children": {"allowed": True},
    "state": {
        "native": "scrollState",
        "kind": "positional",
        "holder": "androidx.compose.foundation.ScrollState",
        "factory": "androidx.compose.foundation.rememberScrollState",
        "initial": "initial",
        "position": "value",
        "drive": "animateScrollTo",
    },
}
"""A scroll-gated column entry: the holder rides the modifier, not a parameter."""

LAZY = {
    "props": {
        "firstVisibleItemIndex": {"type": "integer"},
        "onFirstVisibleItemIndexSettled": {"type": "actionId", "payload": []},
    },
    "children": {"allowed": False},
    "state": {
        "native": "state",
        "kind": "positional",
        "holder": "androidx.compose.foundation.lazy.LazyListState",
        "factory": "androidx.compose.foundation.lazy.rememberLazyListState",
        "initial": "initialFirstVisibleItemIndex",
        "position": "firstVisibleItemIndex",
        "drive": "animateScrollToItem",
    },
}
"""A lazy-list entry: the state parameter takes the holder directly."""


def test_a_slider_is_created_from_its_range_and_reports_where_it_settles() -> None:
    """The slider's family is derived: what fixes the holder keys its factory,
    and its values report together through the holder's settle callback."""
    slider = components()["Slider"]
    adapter = render("Slider", slider)
    assert (
        "val stateValue = key(model.props.steps, model.props.valueRange) {" in adapter
    )
    assert "steps = model.props.steps.toInt()," in adapter
    # A number value may follow a holder stream.
    value = "model.props.value?.let { Wanted(context.number(it).toFloat()) }"
    assert value in adapter
    # No report per change: the settle callback carries them, drives wait on it,
    # and a drive reports where the holder left it.
    assert "answering = model.props.onValueChangeFinished" in adapter
    assert (
        "val stateSettled = context.reportSettled(stateValue, "
        "model.props.onValueChangeFinished, "
        "{ stateValue.onValueChangeFinished = it })" in adapter
    )
    assert "{ stateValue.value = it; stateSettled() }" in adapter
    assert "state = stateValue" in adapter


def test_a_scroll_holder_rides_the_modifier_behind_a_boolean() -> None:
    """The scroll attaches through the modifier, gated by the app's prop."""
    adapter = render("Column", SCROLL)
    assert "val scrollStateValue = context.positional(" in adapter
    assert (
        "model.props.value?.let(::JsonPrimitive), model.props.onValueSettled,"
        in adapter
    )
    assert (
        "modifier = scrollStateValue.attachTo(modifier, model.props.scrollable)"
        in adapter
    )
    # The stem is documentary: Column has no state parameter to fill.
    assert "scrollState =" not in adapter
    assert "com.pycompose.renderer.attachTo" in extra_imports(SCROLL)
    assert "com.pycompose.renderer.attachTo" not in extra_imports(
        components()["Slider"]
    )


def test_a_lazy_list_fills_the_state_parameter() -> None:
    """LazyColumn's state parameter takes the holder directly."""
    adapter = render("LazyColumn", LAZY)
    assert "val stateValue = context.positional(" in adapter
    assert (
        "model.props.firstVisibleItemIndex?.let(::JsonPrimitive), "
        "model.props.onFirstVisibleItemIndexSettled," in adapter
    )
    assert "state = stateValue" in adapter
    assert "firstVisibleItemIndex =" not in adapter


def test_a_tooltip_is_generated_with_its_built_position_and_its_runtime() -> None:
    """The box's provider is the pin's one builder; the host's runtime shows it."""
    adapter = render("TooltipBox", components()["TooltipBox"])
    assert (
        "positionProvider = androidx.compose.material3.TooltipDefaults."
        "rememberTooltipPositionProvider(positioning = positioningValue)" in adapter
    )
    assert (
        "context.tooltipState(model.props.visible, model.props.onVisibilityChange, "
        "model.props.isPersistent)" in adapter
    )
    # Unbound, a dismissal request keeps Compose's own null, which dismisses.
    assert (
        "onDismissRequest = model.props.onDismissRequest?.let { action -> "
        "{ context.actions.dispatch(action) } }" in adapter
    )


def test_a_swipe_holder_reports_the_settled_anchor_and_fills_row_slots() -> None:
    """The enum value and its report are held; both contents use RowScope."""
    entry = components()["SwipeToDismissBox"]
    adapter = render("SwipeToDismissBox", entry)
    assert "val stateValue = context.anchoredState(" in adapter
    assert (
        "{ initial -> initial?.let { androidx.compose.material3."
        "rememberSwipeToDismissBoxState(initialValue = it, "
        "positionalThreshold = positionalThresholdValue) }" in adapter
    )
    # Its factory asks the app's host function how far is far enough, else
    # the pinned default answers.
    assert (
        "positionalThresholdAnswer.value?.call(a0.toDouble())?.let "
        "{ (it as Double).toFloat() } ?: positionalThresholdDefault(a0)" in adapter
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
    assert "com.pycompose.renderer.anchoredState" in extra_imports(entry)


def test_a_held_enum_value_does_not_block_a_mechanical_adapter() -> None:
    """Held props never reach a native parameter, so their type is no obstacle."""
    assert is_mechanical(components()["SwipeToDismissBox"])
