"""Tests for Kotlin adapter generation.

The generator's job is to emit code that compiles, and its failure mode is
generating code that nearly does. Each test below pins one way that happened, so
the next schema change that reintroduces it fails here rather than at
``./gradlew :host:compileDebugKotlin``.

``tools/`` is importable thanks to ``tests/conftest.py``.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from pycompose.schema.codegen.adapters import (
    _held,
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


def test_an_alias_registers_its_schema_name_and_calls_its_native_name() -> None:
    """Two native overloads may share a callable while keeping distinct names.

    The schema key and generated node type use the alias; the recorded source
    alone decides which native callable the adapter invokes.
    """
    entry = copy.deepcopy(components()["NavigationBarItem"])
    entry["source"]["name"] = "NativeNavigationBarItem"
    block = render("AliasedNavigationBarItem", entry)
    assert '.registerRowScoped("AliasedNavigationBarItem")' in block
    assert "val model = node as AliasedNavigationBarItemNode" in block
    assert "\n                NativeNavigationBarItem(\n" in block
    assert "\n                AliasedNavigationBarItem(\n" not in block

    generated = render_file(
        {
            "components": {
                "AliasedNavigationBarItem": entry,
            }
        }
    )
    assert "import androidx.compose.material3.NativeNavigationBarItem" in generated
    assert "import androidx.compose.material3.AliasedNavigationBarItem" not in generated


def test_each_component_is_registered_exactly_once_across_both_files() -> None:
    """No duplicates, no omissions: one adapter per component, in one file."""
    registry = components()
    # No leading dot: TextField's adapter opens a helper, so its register call
    # starts a statement rather than continuing a chain. A scoped component
    # registers through its scope's method, which the same pattern catches.
    pattern = r'register(?:\w+)?\("(\w+)"'
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

    scoped = {
        name: f"{stem}Scope"
        for stem, name in re.findall(
            r'register(\w+?)Scoped\("(\w+)"\)', GENERATED.read_text()
        )
    }
    declared = {
        name: entry["scope"] for name, entry in registry.items() if entry.get("scope")
    }
    assert scoped == declared, (
        f"registered through {scoped}, declared {declared}; a scoped component "
        "registers through its own scope's method"
    )


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


def test_a_registry_with_no_mechanical_adapters_still_renders_the_object() -> None:
    """The builtins call ``GeneratedAdapters.register`` unconditionally.

    A slice that qualifies nothing -- the scaffolding sample is Text plus the
    framework floor -- must still produce a file the host compiles against; an
    absent file is an unresolved reference in BuiltinComponents, and a stale
    file from a previous slice is a hidden fallback (plan 17, step 8.5).
    """
    source = render_file({"components": {}})
    assert "object GeneratedAdapters" in source
    assert "into.generated()" in source


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
    from pycompose.schema.codegen import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    registry["components"]["ModalBottomSheet"]["optIn"] = markers
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
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
        # Everything a state declaration holds -- the desired value, its
        # report, the holder's constructor props and the attach gate -- is
        # passed to a host holder that takes it nullable by design, and so is
        # every prop of a transient component, whose request the host fills.
        held = _held(entry.get("state"))
        if entry.get("transient") is not None:
            held |= set(entry["props"])
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


def test_a_required_nullable_scalar_is_passed_through() -> None:
    """``Icon.contentDescription`` is ``String?`` and has no default to omit.

    The pinned parameter takes no default, so absence is not one of its states:
    the wire has to state a description or an explicit null, and what the model
    holds is that nullable value rather than the ``OptionalValue`` an optional
    nullable prop gets.
    """
    block = render("Icon", components()["Icon"])
    assert "contentDescription = model.props.contentDescription" in block


def test_an_int_scalar_is_narrowed_for_compose() -> None:
    """The wire carries an integer as ``Long``; this parameter is Kotlin ``Int``."""
    block = render("PrimaryTabRow", components()["PrimaryTabRow"])
    assert "selectedTabIndex = model.props.selectedTabIndex.toInt()" in block


def test_a_dp_default_is_the_extension_property_it_names() -> None:
    """A literal dp default must not invent a synthetic import alias."""
    surface = components()["Surface"]
    assert surface["props"]["shadowElevation"]["nativeDefault"] == "(0).dp"
    block = render("Surface", surface)
    assert "else (0).dp" in block
    assert "default_androidx" not in block


def test_an_icon_is_resolved_from_the_pinned_vocabulary() -> None:
    """The wire names an icon; the host supplies the pinned ``ImageVector``."""
    block = render("Icon", components()["Icon"])
    assert "ValueResolver.imageVector(model.props.imageVector).getOrThrow()" in block
    # ``Icon`` tints with the ambient content colour unless the app states one,
    # so the fallback is the pinned default and not a generated guess.
    assert "androidx.compose.material3.LocalContentColor.current" in block


def test_nullable_shapes_are_kept_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two nullable shapes fit different parameters, so both are checked.

    A required nullable prop is handed over as it stands, which only lines up
    where the wire value *is* the native value: an undecoded scalar. An optional
    nullable prop is the ``OptionalValue`` form the value family's adapter
    implements, where absence and an explicit null are two facts. Anything else
    would be passed where it does not fit or dropped silently.
    """
    from pycompose.schema.codegen import main, rules

    registry = json.loads(SCHEMA_PATH.read_text())
    registry["components"]["Text"]["props"]["color"] = {
        "type": "string",
        "nullable": True,
    }
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    with pytest.raises(SystemExit, match="absent/null distinction"):
        main.load_registry()

    registry = json.loads(SCHEMA_PATH.read_text())
    registry["components"]["Icon"]["props"]["imageVector"]["nullable"] = True
    path.write_text(json.dumps(registry))
    with pytest.raises(SystemExit, match="must be an undecoded scalar"):
        main.load_registry()
