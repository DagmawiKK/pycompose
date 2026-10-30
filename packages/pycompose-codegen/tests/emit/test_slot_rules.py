"""Declared slots the generator refuses, and the models that carry their children.

A slot it cannot render faithfully is refused where the schema is read, not
guessed into an adapter that composes the wrong subtree.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# The codegen refuses a slot it cannot render faithfully
# ---------------------------------------------------------------------------


def _load_with(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """Validate the catalog after one deliberate change.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch fixture.
        mutate: Applies the change to the loaded registry.
    """
    import json

    from pycompose_codegen.emit import main, rules

    registry = json.loads(
        (Path(__file__).resolve().parents[4] / "schema/catalog.lock.json").read_text()
    )
    mutate(registry)
    path = tmp_path / "components.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setattr(rules, "SCHEMA_PATH", path)
    main.load_registry()


def _slot(registry: dict[str, Any], component: str, name: str) -> dict[str, Any]:
    """Return one mutably loaded slot entry.

    Args:
        registry: The loaded catalog.
        component: Component owning the slot.
        name: The slot name.

    Returns:
        The slot's raw entry, for the caller to break.
    """
    return registry["components"][component]["slots"][name]


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        (
            lambda registry: _slot(registry, "Scaffold", "topBar").update(
                kind="canvas"
            ),
            "'kind' must be one of content, items, keyed",
        ),
        (
            # Keyed content is a children form; no adapter renders a keyed slot.
            lambda registry: _slot(registry, "Scaffold", "topBar").update(kind="keyed"),
            "must be content or items",
        ),
        (
            lambda registry: _slot(registry, "Scaffold", "topBar").update(
                native="containerColor"
            ),
            "repeats another parameter",
        ),
        (
            lambda registry: _slot(registry, "Scaffold", "topBar").update(
                native="content"
            ),
            "repeats another parameter",
        ),
        (
            lambda registry: _slot(registry, "FilterChip", "leadingIcon").update(
                consume="paddingValues"
            ),
            "needs a non-nullable slot",
        ),
        (
            lambda registry: _slot(registry, "Scaffold", "topBar").update(unknown=True),
            "unknown keys",
        ),
    ],
)
def test_the_codegen_refuses_an_unrenderable_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    break_it: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    """A slot the generator cannot render faithfully is refused, not guessed.

    The failure has to be raised where the schema is read: an adapter emitted
    from a slot the generator half-understood compiles and then composes the
    wrong subtree, which is worse than not building at all.
    """
    with pytest.raises(SystemExit, match=expected):
        _load_with(tmp_path, monkeypatch, break_it)


def test_the_codegen_refuses_a_slot_named_like_a_prop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slot shadowing a prop would silently drop one of the two arguments."""
    with pytest.raises(SystemExit, match="collides with a prop"):
        _load_with(
            tmp_path,
            monkeypatch,
            lambda registry: registry["components"]["Scaffold"]["slots"].update(
                {"containerColor": {"native": "containerColorSlot"}}
            ),
        )


# ---------------------------------------------------------------------------
# A slot-bearing component carries its children, primary or not
# ---------------------------------------------------------------------------


def test_a_slot_bearing_component_carries_its_children() -> None:
    """The model accepts what the wire permits: slot children need the list.

    A component may forbid primary children and still declare slots -- a chip's
    leading icon, a bar item's label -- and those children ride the same
    ``children`` list as primary ones, because the wire has one place for a
    child. A model without the field rejects the snapshot before any adapter
    sees it, so the declared slot is the fact that decides, not
    ``children.allowed``.
    """
    from pycompose_codegen.emit.emit_kotlin import render_kotlin_models

    models = render_kotlin_models(
        {
            "actions": {},
            "components": {
                "Leaf": {"props": {}, "children": {"allowed": False}},
                "Slotted": {
                    "props": {},
                    "children": {"allowed": False},
                    "slots": {"icon": {"native": "icon"}},
                },
                "Parent": {"props": {}, "children": {"allowed": True}},
            },
        }
    )
    carrying = (
        "    override val props: {name}Props,\n"
        "    override val children: List<UiNode> = emptyList(),\n"
    )
    assert carrying.format(name="Slotted") in models
    assert carrying.format(name="Parent") in models
    assert (
        "data class Leaf(\n"
        "    override val id: String,\n"
        "    override val props: LeafProps,\n"
        "    override val slot: String? = null,\n"
        ") : UiNode {\n"
        "    override val children: List<UiNode> get() = emptyList()"
    ) in models
