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
    assert "contentDescription = it.jsonPrimitive.content" in SOURCE
    assert '"radioButton" -> androidx.compose.ui.semantics.Role.RadioButton' in SOURCE
    assert "heading()" in SOURCE
    assert "import androidx.compose.ui.semantics.traversalIndex" in SOURCE
