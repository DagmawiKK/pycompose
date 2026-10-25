"""Slot, scope and provider-children rendering of generated adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_generated_adapters import (
    SCHEMA_PATH,
    components,
)

from pycompose.schema.codegen.adapters import (
    composables,
    render,
)


def test_a_flattened_slot_renders_its_declared_composable() -> None:
    """``Button`` has no ``text`` parameter; text is a content lambda."""
    block = render("Button", components()["Button"])
    assert "Text(model.props.text)" in block
    assert "text = model.props.text" not in block
    # Trailing lambda, because Button takes content positionally.
    assert ") {\n                    Text(model.props.text)\n                }" in block


def test_a_named_slot_is_passed_by_name() -> None:
    """``FilterChip`` names its slot ``label``, so it is an argument, not trailing."""
    block = render("FilterChip", components()["FilterChip"])
    assert "label = { Text(model.props.label) }" in block


def test_a_slot_declares_the_import_its_content_needs() -> None:
    """``Button`` does not compile without ``Text`` in scope."""
    assert "Text" in composables("Button", components()["Button"])
    # The component's own name is not an extra import of itself.
    assert "Button" not in composables("Button", components()["Button"])


def test_an_optional_slot_is_not_generated() -> None:
    """``TextField.label`` is optional, so it needs a null check -- a decision."""
    entry = components()["TextField"]
    assert entry["props"]["label"].get("content")
    assert render("TextField", entry) == ""


def test_primary_children_reach_the_declared_parameter() -> None:
    """The primary children go to the parameter the schema names, by name.

    Not as a trailing lambda: the schema says which parameter receives them and
    says nothing about where that parameter sits in the signature.
    """
    block = render("Column", components()["Column"])
    assert "content = { context.childrenIn(this, model.children) }," in block
    # A parent whose lambda carries no scope passes nothing down.
    drawer = components()["DismissibleNavigationDrawer"]
    block = render("DismissibleNavigationDrawer", drawer)
    assert "content = { context.children(model.children) }" in block


def test_a_named_slot_reaches_its_native_parameter() -> None:
    """Scaffold's four content parameters are four slots, not one subtree.

    The lambda has to *invoke* the slot: evaluating it builds the subtree and
    drops it, which compiles and renders nothing.
    """
    block = render("Scaffold", components()["Scaffold"])
    for native in ("bottomBar", "floatingActionButton", "snackbarHost", "topBar"):
        assert (
            f'{native} = {{ context.slot(model.children, "{native}")?.invoke() }}'
            in block
        )


def test_search_bars_separate_the_input_field_from_the_result_content() -> None:
    """A search bar's input is a slot; results compose in the same ColumnScope."""
    for name in ("SearchBar", "DockedSearchBar"):
        block = render(name, components()[name])
        assert (
            'inputField = { context.slot(model.children, "inputField")?.invoke() }'
            in block
        )
        assert "content = { context.childrenIn(this, model.children) }" in block


def test_a_nullable_slot_keeps_compose_default() -> None:
    """FilterChip's icons are nullable, so empty must stay null.

    An empty lambda reserves icon space for nothing, which is a layout change
    the app never asked for.
    """
    block = render("FilterChip", components()["FilterChip"])
    assert 'leadingIcon = context.slot(model.children, "leadingIcon")' in block
    assert 'trailingIcon = context.slot(model.children, "trailingIcon")' in block


def test_a_consumed_scope_is_applied_by_the_adapter() -> None:
    """Scaffold hands PaddingValues down; the app must not apply it twice."""
    from pycompose.schema.codegen.adapters import extra_imports

    entry = components()["Scaffold"]
    block = render("Scaffold", entry)
    assert "content = { padding -> Column(Modifier.padding(padding)) {" in block
    assert "androidx.compose.foundation.layout.padding" in extra_imports(entry)
    assert "androidx.compose.foundation.layout.Column" in extra_imports(entry)
    assert "androidx.compose.ui.Modifier" in extra_imports(entry)


def test_a_lazy_slot_lists_children_as_a_keyed_window() -> None:
    """LazyColumn's content is a window of keyed items the host asks for."""
    from pycompose.schema.codegen.adapters import extra_imports

    entry = components()["LazyColumn"]
    block = render("LazyColumn", entry)
    assert (
        "content = { windowedItems(context, model.children.unslotted(), "
        "model.props.itemCount, model.props.itemOffset) }"
    ) in block
    assert "context.RequestWindows(stateValue, model.props.window" in block
    assert "com.pycompose.renderer.windowedItems" in extra_imports(entry)
    # An extension resolves only where it is imported.
    assert "com.pycompose.renderer.unslotted" in extra_imports(entry)


def test_a_named_items_slot_lists_its_own_nodes() -> None:
    """A lazy slot lists the slot's children, not the primary ones."""
    from pycompose.schema.codegen.adapters import extra_imports

    entry = components()["Column"]
    entry["slots"] = {"header": {"native": "header", "kind": "items"}}
    block = render("Column", entry)
    assert 'items(model.children.inSlot("header"), key = { it.id })' in block
    assert "com.pycompose.renderer.inSlot" in extra_imports(entry)


def test_an_undeclared_slot_kind_is_refused() -> None:
    """Rather than emit Kotlin for a shape the generator does not know."""
    entry = components()["Scaffold"]
    entry["slots"]["topBar"]["kind"] = "canvas"
    assert render("Scaffold", entry) == ""


def test_a_scoped_component_registers_through_its_scope() -> None:
    """``NavigationBarItem`` is ``RowScope.NavigationBarItem`` in the pin.

    Its receiver cannot be invented at the call site, so the adapter is not a
    plain table entry: it registers through the scope's method and is looked up
    only inside a lambda that carries that receiver.
    """
    block = render("NavigationBarItem", components()["NavigationBarItem"])
    assert '.registerScoped<RowScope>("NavigationBarItem")' in block


def test_a_provider_hands_its_children_the_receiver() -> None:
    """A parent whose content lambda carries a receiver passes it down.

    The receiver is what makes a scoped child composable at all, so a provided
    scope composes the children inside it rather than beside it.
    """
    for name in ("Box", "Column", "Row"):
        block = render(name, components()[name])
        assert "context.childrenIn(this, model.children)" in block, name


def test_a_scoped_named_slot_hands_its_receiver_to_its_children() -> None:
    """``actions``, ``header`` and ``badge`` carry receivers of their own.

    A named slot is a separate lambda from the primary content, so it needs a
    scoped renderer too; the non-null form keeps an empty lambda so the native
    empty-lambda default survives.
    """
    top = render("TopAppBar", components()["TopAppBar"])
    assert 'actions = context.slotIn<RowScope>(model.children, "actions") ?: {}' in top
    assert (
        'navigationIcon = { context.slot(model.children, "navigationIcon")?.invoke() }'
        in top
    )
    rail = render("NavigationRail", components()["NavigationRail"])
    assert 'header = context.slotIn<ColumnScope>(model.children, "header")' in rail
    badge = render("BadgedBox", components()["BadgedBox"])
    assert 'badge = context.slotIn<BoxScope>(model.children, "badge") ?: {}' in badge


def test_the_adapters_import_every_receiver_they_name() -> None:
    """A scope is its receiver class, so the file imports it, whatever library."""
    from pycompose.schema.codegen.adapters import render_file

    source = render_file(json.loads(SCHEMA_PATH.read_text()))
    for scope in (
        "androidx.compose.foundation.layout.RowScope",
        "androidx.compose.material3.ExposedDropdownMenuBoxScope",
    ):
        assert f"import {scope}\n" in source
    # A member of its scope is called on the receiver, so it is never imported.
    assert "import androidx.compose.material3.ExposedDropdownMenu\n" not in source


@pytest.mark.parametrize(
    ("component", "change", "message"),
    [
        ("NavigationBarItem", {"scope": "TouchScope"}, "must name a receiver class"),
        (
            "Card",
            {"children": {"allowed": True, "kind": "content", "provides": "Touch"}},
            "children.provides must name a receiver class",
        ),
        (
            "Card",
            {
                "children": {
                    "allowed": True,
                    "kind": "content",
                    "provides": "androidx.compose.foundation.layout.RowScope",
                    "consume": "paddingValues",
                }
            },
            "cannot consume and provide a scope",
        ),
        (
            "Card",
            {
                "children": {
                    "allowed": True,
                    "kind": "items",
                    "provides": "androidx.compose.foundation.layout.RowScope",
                }
            },
            "needs the content kind",
        ),
        (
            "Scaffold",
            {"slots": {"topBar": {"native": "topBar", "provides": "Touch"}}},
            "'provides' must name a receiver class",
        ),
        (
            "Scaffold",
            {
                "slots": {
                    "topBar": {
                        "native": "topBar",
                        "provides": "androidx.compose.foundation.layout.RowScope",
                        "consume": "paddingValues",
                    }
                }
            },
            "cannot consume and provide a scope",
        ),
        (
            "Scaffold",
            {
                "slots": {
                    "topBar": {
                        "native": "topBar",
                        "kind": "items",
                        "provides": "androidx.compose.foundation.layout.RowScope",
                    }
                }
            },
            "needs the content kind",
        ),
    ],
)
def test_the_schema_refuses_a_scope_it_cannot_wire(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    component: str,
    change: dict,
    message: str,
) -> None:
    """A scope names its receiver class on both ends, so a typo fails at codegen."""
    from pycompose.schema.codegen import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    registry["components"][component].update(change)
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match=message):
        main.load_registry()


def test_a_component_taking_no_modifier_sits_in_a_box_wearing_the_nodes() -> None:
    """``DisableSelection`` has no modifier; the wire still carries one per node."""
    entry = components()["DisableSelection"]
    assert entry["boxed"] is True
    block = render("DisableSelection", entry)
    assert "Box(modifier = modifier) {" in block
    native = block[block.index("DisableSelection(") :]
    assert "modifier" not in native
