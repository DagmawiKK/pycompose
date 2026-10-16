"""Tests for Kotlin adapter generation.

The generator's job is to emit code that compiles, and its failure mode is
generating code that nearly does. Each test below pins one way that happened, so
the next schema change that reintroduces it fails here rather than at
``./gradlew :host:compileDebugKotlin``.

``tools/`` is importable thanks to ``tests/conftest.py``.
"""

from __future__ import annotations

import json
import pathlib
import re
from pathlib import Path
from typing import Any

import pytest

from pycompose.schema.codegen.adapters import (
    composables,
    is_mechanical,
    render,
    render_file,
)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "components.json"
GENERATED = (
    Path(__file__).resolve().parent.parent
    / "android/host/src/main/kotlin/com/pycompose/host/ui/GeneratedAdapters.kt"
)
MANUAL = (
    Path(__file__).resolve().parent.parent
    / "android/host/src/main/kotlin/com/pycompose/host/ui/BuiltinComponents.kt"
)


def components() -> dict[str, Any]:
    """Return the schema's component entries, keyed by name.

    Returns:
        Every component entry in ``components.json``.
    """
    return json.loads(SCHEMA_PATH.read_text())["components"]


# ---------------------------------------------------------------------------
# The marker decides, and the marker is honoured
# ---------------------------------------------------------------------------


def test_a_component_marked_manual_generates_nothing() -> None:
    """``adapter: manual`` must be load-bearing, not decoration."""
    registry = components()
    marked = [n for n, e in registry.items() if e.get("adapter") == "manual"]
    assert marked, "expected some components to be manual"
    for name in marked:
        assert not is_mechanical(registry[name]), f"{name} is marked manual"
        assert render(name, registry[name]) == "", f"{name} generated an adapter"


def test_every_component_is_either_generated_or_has_a_stated_reason() -> None:
    """No component may fall through both paths unnoticed.

    This is the gap that produced a blank screen once: a component in neither
    file, discovered by a user rather than by a test. The reason has to be
    *stated* rather than merely detectable, so that reading the schema tells you
    why a component is hand-written.
    """
    registry = components()
    for name, entry in sorted(registry.items()):
        block = render(name, entry)
        assert bool(block) == is_mechanical(
            entry
        ), f"{name}: rendered={bool(block)} but is_mechanical={is_mechanical(entry)}"
        if not block:
            # A wrapper delegates the decision; anything else is a decision the
            # schema has to own outright.
            assert entry.get("adapter") == "manual" or entry.get(
                "wrapper"
            ), f"{name} is hand-written but its entry does not say why"


def test_declaring_children_makes_a_component_generatable() -> None:
    """Children used to be the widest exclusion; declaring them removes the guess.

    Each of these was hand-written because its subtree had nowhere declared to
    go. None of them carries a decision now: the schema says which parameter
    receives which children, and the generator follows it.
    """
    registry = components()
    for name in ("Box", "Column", "LazyColumn", "Row", "Scaffold"):
        assert render(name, registry[name]), f"{name} should be generated"


def test_the_committed_file_matches_what_the_generator_produces() -> None:
    """Generated Kotlin is a build artifact; drift is a failed --check."""
    assert GENERATED.exists(), "gen.py did not emit GeneratedAdapters.kt"
    committed = GENERATED.read_text()
    assert (
        render_file({"components": components()}).strip() == committed.strip()
    ), "GeneratedAdapters.kt is stale; run python tools/schema/gen.py"


def test_each_component_is_registered_exactly_once_across_both_files() -> None:
    """No duplicates, no omissions: one adapter per component, in one file."""
    registry = components()
    # No leading dot: TextField's adapter opens a helper, so its register call
    # starts a statement rather than continuing a chain.
    pattern = r'register\("(\w+)"'
    generated_names = re.findall(pattern, GENERATED.read_text())
    manual_names = re.findall(pattern, MANUAL.read_text())

    assert len(generated_names) == len(set(generated_names)), "duplicate in generated"
    assert len(manual_names) == len(set(manual_names)), "duplicate in manual"

    both = set(generated_names) & set(manual_names)
    assert not both, f"registered twice: {sorted(both)}"

    covered = set(generated_names) | set(manual_names)
    assert covered == set(registry), (
        f"uncovered: {sorted(set(registry) - covered)}; "
        f"unknown: {sorted(covered - set(registry))}"
    )


# ---------------------------------------------------------------------------
# Component opt-ins: the pinned declaration decides
# ---------------------------------------------------------------------------


def test_the_committed_file_declares_the_markers_its_components_require() -> None:
    """A component that needs an opt-in is still one anonymous builder.

    The markers are a property of the *file*, not of the single adapter that
    first needed one, so the union is emitted once -- and it is the union of the
    components the file actually renders.
    """
    markers = sorted(
        {
            marker
            for entry in components().values()
            if is_mechanical(entry)
            for marker in entry.get("optIn", [])
        }
    )
    assert markers, "expected the catalog to declare component opt-ins"
    annotation = "@file:OptIn(" + ", ".join(f"{m}::class" for m in markers) + ")"
    assert annotation in GENERATED.read_text()


def test_the_file_annotation_precedes_the_package_and_imports() -> None:
    """A file annotation after the package directive does not compile."""
    source = GENERATED.read_text()
    annotation = source.index("@file:OptIn(")
    assert annotation < source.index("package ")
    assert annotation < source.index("\nimport ")


def test_a_component_without_a_marker_contributes_no_annotation() -> None:
    """An opt-in the file does not need is a stale permission, not a harmless extra."""
    source = render_file({"components": {"Column": components()["Column"]}})
    assert "Column(" in source
    assert "@file:OptIn" not in source


def test_a_manual_components_markers_never_reach_the_generated_file() -> None:
    """A hand-written adapter declares its own markers, in its own file."""
    declaration = {
        **components()["Button"],
        "adapter": "manual",
        "optIn": ["androidx.compose.material3.ExperimentalMaterial3Api"],
    }
    source = render_file(
        {"components": {"Column": components()["Column"], "Button": declaration}}
    )
    assert "Column(" in source
    assert "Button(" not in source
    assert "@file:OptIn" not in source


@pytest.mark.parametrize(
    "markers",
    [
        ["androidx.compose.material3.ExperimentalMaterial3Api"] * 2,
        ["z.Marker", "a.Marker"],
        [""],
    ],
)
def test_the_codegen_refuses_an_unproven_component_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, markers: list[str]
) -> None:
    """A marker list is a promise that these, exactly, compile the file."""
    from pycompose.schema.codegen import main

    registry = json.loads(SCHEMA_PATH.read_text())
    registry["components"]["ModalBottomSheet"]["optIn"] = markers
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(main, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="optIn must be sorted"):
        main.load_registry()


def test_the_runtime_registry_round_trips_a_components_opt_in() -> None:
    """The registry type keeps the markers a schema reader can trust."""
    from pycompose.core.registry_types import ComponentSpec
    from pycompose.errors import ComponentRegistryError

    declaration = {
        **components()["ModalBottomSheet"],
        "props": {},
        "children": {"allowed": True},
    }
    spec = ComponentSpec.from_mapping("ModalBottomSheet", declaration)
    assert spec.opt_in == ("androidx.compose.material3.ExperimentalMaterial3Api",)
    assert spec.to_mapping()["optIn"] == [
        "androidx.compose.material3.ExperimentalMaterial3Api"
    ]
    for malformed in (3, [1], {}):
        with pytest.raises(ComponentRegistryError, match="'optIn' must be a string"):
            ComponentSpec.from_mapping(
                "ModalBottomSheet", {**declaration, "optIn": malformed}
            )


# ---------------------------------------------------------------------------
# Nullability: the mistake that produced "does not compile"
# ---------------------------------------------------------------------------


def test_no_optional_prop_is_passed_through() -> None:
    """A nullable Kotlin property must never reach Compose as a non-null.

    ``Boolean?`` into a ``Boolean`` parameter does not compile. A prop may only
    be passed when the schema marks it required or gives it a default; anything
    else is omitted so Compose's own default applies. A decoded prop is passed
    all the same, because its resolver takes the nullable wire value and each
    decoding path handles absence itself, and a prop a state declaration holds
    is passed to a host holder that takes it nullable by design: absent means
    the app said nothing about that half of the protocol.
    """
    registry = components()
    for name, entry in sorted(registry.items()):
        block = render(name, entry)
        if not block:
            continue
        state = entry.get("state") or {}
        held = {state.get("value"), state.get("report")} - {None}
        for prop, spec in entry["props"].items():
            if prop in held:
                continue
            referenced = re.search(rf"model\.props\.{re.escape(prop)}\b", block)
            if referenced is None:
                continue
            if (
                spec["type"] in ("actionId", "modifier")
                or spec.get("content")
                or spec.get("decode")
            ):
                continue
            assert (
                spec.get("required") or "default" in spec or "nativeDefault" in spec
            ), (
                f"{name}.{prop} is optional and has no default, "
                "so the generated model types it nullable"
            )


def test_an_omitted_optional_prop_is_simply_absent() -> None:
    """A prop with a default is passed; one without is left to Compose."""
    block = render("Button", components()["Button"])
    assert "enabled = model.props.enabled" in block

    # TextButton carries no optional-without-default scalar to omit, so assert
    # the rule on a prop that has one instead. Action ids are read by the
    # callback and interaction locals; the rule here is about values passed
    # straight to Compose.
    block = render("FilterChip", components()["FilterChip"])
    for prop, spec in components()["FilterChip"]["props"].items():
        if spec["type"] == "actionId":
            continue
        if not spec.get("required") and "default" not in spec:
            assert f"model.props.{prop}" not in block


# ---------------------------------------------------------------------------
# Content slots: Compose has no Button.text
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Declared slots: Compose has no single "children"
# ---------------------------------------------------------------------------


def test_primary_children_reach_the_declared_parameter() -> None:
    """The primary children go to the parameter the schema names, by name.

    Not as a trailing lambda: the schema says which parameter receives them and
    says nothing about where that parameter sits in the signature.
    """
    block = render("Column", components()["Column"])
    assert "content = { context.children(model.children) }," in block


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


def test_a_lazy_slot_lists_children_as_keyed_items() -> None:
    """LazyColumn's content is a lazy scope; keys keep state across recomposition."""
    from pycompose.schema.codegen.adapters import extra_imports

    entry = components()["LazyColumn"]
    block = render("LazyColumn", entry)
    assert (
        "content = { items(context.unslotted(model.children), key = { it.id })" in block
    )
    assert "androidx.compose.foundation.lazy.items" in extra_imports(entry)


def test_a_named_items_slot_lists_its_own_nodes() -> None:
    """A lazy slot lists the slot's children, not the primary ones."""
    entry = components()["Column"]
    entry["slots"] = {"header": {"native": "header", "kind": "items"}}
    block = render("Column", entry)
    assert (
        'items(context.slotNodes(model.children, "header"), key = { it.id })' in block
    )


def test_an_undeclared_slot_kind_is_refused() -> None:
    """Rather than emit Kotlin for a shape the generator does not know."""
    entry = components()["Scaffold"]
    entry["slots"]["topBar"]["kind"] = "canvas"
    assert render("Scaffold", entry) == ""


# ---------------------------------------------------------------------------
# Callback arity
# ---------------------------------------------------------------------------


def test_a_payloadless_callback_dispatches_the_bare_action() -> None:
    """``onClick`` takes nothing, so there is nothing to report."""
    block = render("Button", components()["Button"])
    assert "onClick = { context.actions.dispatch(model.props.onClick) }" in block


def test_a_callback_with_a_payload_reports_it() -> None:
    """``onCheckedChange`` hands back the new value and must report it.

    Omitting the payload compiles and then does nothing: the app never learns
    the checkbox moved. Passing a ``String`` where a ``Boolean`` belongs does not
    compile at all. Both failures trace back to the same missing declaration.
    """
    block = render("Checkbox", components()["Checkbox"])
    assert (
        "onCheckedChange = { value -> "
        "context.event(model.props.onCheckedChange, JsonPrimitive(value)) }" in block
    )


def test_a_payload_type_the_generator_cannot_map_is_refused() -> None:
    """Rather than guess, decline."""
    entry = components()["Checkbox"]
    entry["props"]["onCheckedChange"]["payload"] = [{"name": "value", "type": "color"}]
    assert render("Checkbox", entry) == ""


# ---------------------------------------------------------------------------
# The schema rejects nonsense
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("prop", "why"),
    [
        ({"type": "actionId", "content": {"composable": "Text"}}, "slots flatten text"),
        (
            {"type": "string", "payload": [{"name": "value", "type": "boolean"}]},
            "only callbacks carry payloads",
        ),
        ({"type": "string", "content": {"composable": ""}}, "needs a composable"),
        (
            {"type": "actionId", "payload": [{"name": "", "type": "boolean"}]},
            "payload fields need names",
        ),
        (
            {
                "type": "actionId",
                "payload": [
                    {"name": "value", "type": "boolean"},
                    {"name": "value", "type": "string"},
                ],
            },
            "payload field names must be unique",
        ),
    ],
)
def test_the_registry_refuses_an_impossible_prop(prop: dict, why: str) -> None:
    """A prop that cannot exist is refused at parse time, not at build time."""
    from pycompose.core.registry_types import PropDef
    from pycompose.errors import ComponentRegistryError

    try:
        PropDef.from_mapping(prop, where="test")
    except ComponentRegistryError:
        return
    pytest.fail(f"{prop} was accepted, but {why}")


def test_the_generated_file_imports_only_what_it_uses() -> None:
    """A wildcard or a stale import is the kind of thing spotless fixes silently."""
    source = GENERATED.read_text()
    body = source.split("object GeneratedAdapters", 1)[1]
    for line in source.splitlines():
        if line.startswith("import "):
            # An aliased import ends in "as Alias", and it is the alias the body
            # has to use, not the class name.
            simple = (
                line.rsplit(" as ", 1)[-1]
                if " as " in line
                else line.rsplit(".", 1)[-1]
            )
            assert re.search(rf"\b{re.escape(simple)}\b", body), f"unused: {line}"


# ---------------------------------------------------------------------------
# Decoders: the prop types whose wire form is not their Kotlin type
# ---------------------------------------------------------------------------


def test_every_enum_color_and_resource_prop_declares_its_decoder() -> None:
    """Without a `decode`, a generator cannot tell one enum family from another.

    `PropResolver` knows how to turn `"start"` into an `Alignment.Horizontal`,
    but nothing in the data says `["start","center","end"]` means *horizontal*
    rather than some other family with the same three values. Declared per prop,
    never inferred from the value set: inference breaks silently the day two
    families share a value set, and the failure is a wrong alignment rather than
    an error.
    """
    registry = components()
    for name, entry in sorted(registry.items()):
        for prop, spec in entry["props"].items():
            if spec["type"] in {"enum", "color", "resource"}:
                assert spec.get(
                    "decode"
                ), f"{name}.{prop} is a {spec['type']} with no decoder"


def test_a_decoder_binds_to_a_resolver_that_exists() -> None:
    """A typo'd decoder name generates Kotlin that does not compile."""
    from pycompose.schema.codegen.adapters import RESOLVER_FALLBACK, RESOLVER_RETURN

    declared = {
        spec["decode"]
        for entry in components().values()
        for spec in entry["props"].values()
        if spec.get("decode")
    }
    assert declared, "expected the catalog to declare decoders"
    for decoder in declared:
        assert decoder in RESOLVER_RETURN, decoder
        assert decoder in RESOLVER_FALLBACK, decoder
    # Everything except the resource family resolves through PropResolver.
    for decoder in declared - {"resourceText", "resourceImage", "resourceFont"}:
        source = (
            pathlib.Path("android/renderer/src/main/kotlin")
            / "com/pycompose/renderer/PropResolver.kt"
        ).read_text()
        assert f"fun {decoder}(" in source, f"{decoder} has no resolver"


def decoded_example() -> tuple[str, str]:
    """Return a component that is generated and carries a decoded prop.

    Text and Image both declare `wrapper` and so are hand-written by design;
    testing decoded output through them would assert nothing about the
    generator. A minimal entry is rendered for real instead, so the assertion
    covers the generator's own emission rather than a hand-written adapter.

    Returns:
        The component name and its rendered adapter.
    """
    from pycompose.schema.codegen.adapters import render as render_one

    entry = {
        "children": {"allowed": False},
        "props": {
            "resource": {
                "type": "resource",
                "values": ["drawable", "asset"],
                "decode": "resourceImage",
                "required": True,
            },
            "contentDescription": {"type": "string"},
        },
    }
    return "Image", render_one("Image", entry)


def test_a_decoded_prop_becomes_a_local_not_an_inline_call() -> None:
    """`textStyle` reads MaterialTheme, which is only in scope in composition.

    Inlining it into an argument list makes the call non-composable, which the
    compiler rejects -- so decoded props bind to a `val` first.
    """
    name, block = decoded_example()
    assert block, f"{name} should render"
    assert (
        "val resourceValue: androidx.compose.ui.graphics.painter.Painter? = "
        "resources?.image(" in block
    )
    assert "resource = resourceValue" in block


def test_a_bad_resource_degrades_rather_than_throwing() -> None:
    """ADR-0005: Compose must never see an exception from a malformed prop."""
    _, block = decoded_example()
    assert ".getOrNull()" in block


def test_an_optional_decoded_prop_is_not_passed_to_a_non_null_resolver() -> None:
    """`PropResolver.color` takes a String; a nullable would not compile."""
    from pycompose.schema.codegen.adapters import render as render_one

    entry = {
        "children": {"allowed": False},
        "props": {
            "text": {"type": "string", "required": True},
            "color": {"type": "color", "decode": "color"},
        },
    }
    block = render_one("Text", entry)
    assert "model.props.color?.takeIf" in block


def test_a_wrapped_component_is_not_reduced_to_resolved_values() -> None:
    """Text loads off the Compose thread; a String? cannot express that."""
    for name in ("Text", "Image"):
        entry = components()[name]
        assert entry.get("wrapper"), f"{name} should declare a wrapper"
        assert render(name, entry) == "", f"{name} must not be generated"


def test_the_registry_refuses_a_decoder_on_a_type_that_needs_none() -> None:
    """A decode on a plain string is a category error, not a harmless extra."""
    from pycompose.core.registry_types import PropDef
    from pycompose.errors import ComponentRegistryError

    with pytest.raises(ComponentRegistryError):
        PropDef.from_mapping({"type": "string", "decode": "color"}, where="test")


def test_the_registry_refuses_an_unknown_decoder() -> None:
    from pycompose.core.registry_types import PropDef
    from pycompose.errors import ComponentRegistryError

    with pytest.raises(ComponentRegistryError):
        PropDef.from_mapping({"type": "enum", "decode": "diagonal"}, where="test")
