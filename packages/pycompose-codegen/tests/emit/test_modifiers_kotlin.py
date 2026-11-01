"""Every modifier the catalog declares is applied by generated Kotlin."""

from __future__ import annotations

import json
from pathlib import Path

from pycompose_codegen.emit.modifiers_kotlin import render_modifiers

LOCK = Path(__file__).resolve().parents[4] / "schema" / "catalog.lock.json"
SOURCE = render_modifiers(json.loads(LOCK.read_text()))


def test_every_policy_modifier_has_a_branch() -> None:
    policy = json.loads((LOCK.parent / "policy" / "catalog.json").read_text())
    for name in policy["modifiers"]:
        assert f'"{name}" ->' in SOURCE, name


def test_a_bare_dp_calls_the_overload_taking_one_dp() -> None:
    assert "Modifier.padding(all = " in SOURCE
    assert "Modifier.padding(" in SOURCE and "paddingValues = " in SOURCE


def test_a_click_dispatches_its_action_id_rather_than_running_python() -> None:
    assert "{ dispatch(value.jsonPrimitive.content) }" in SOURCE


def test_semantics_sets_the_receivers_members() -> None:
    assert "Modifier.semantics(properties = {" in SOURCE
    assert "contentDescriptionValue?.let { contentDescription = it }" in SOURCE
    assert '"radioButton" -> androidx.compose.ui.semantics.Role.RadioButton' in SOURCE
    assert "heading()" in SOURCE
    assert "import androidx.compose.ui.semantics.traversalIndex" in SOURCE


def test_a_bound_prop_is_read_in_the_phase_the_pin_defers_it_to() -> None:
    """``graphicsLayer`` draws, so its bound props redraw alone."""
    assert "com.pycompose.program.Phase.Draw" in SOURCE
    assert "Modifier.graphicsLayer(block = {" in SOURCE
    assert "alpha = alphaState?.value ?: 1.0f" in SOURCE


def test_a_layout_prop_is_read_where_the_pin_answers_with_it() -> None:
    """``offset`` asks for an ``IntOffset``; the props are read laying out."""
    assert "com.pycompose.program.Phase.Layout" in SOURCE
    assert "Modifier.offset(offset = {" in SOURCE
    assert "x = (xState?.value ?: (0).dp).roundToPx()," in SOURCE
    assert "import androidx.compose.ui.unit.IntOffset" in SOURCE
