"""The component compiler: policy overlay semantics and lock reproduction."""

from __future__ import annotations

import os

import pytest

from tools.composegen.lock import LOCK, ROOT, dumps, generate
from tools.composegen.policy import diff, load, merge, redundant
from tools.composegen.signatures import render, type_text
from tools.schema.classpath_dump import DUMP_DIR, inventory
from tools.schema.classpath_types import COMPOSABLE, EXTENSION, KotlinType


def test_a_merge_patch_merges_objects_and_deletes_on_null() -> None:
    base = {"props": {"text": {"type": "string"}, "style": {"type": "enum"}}}
    patch = {"props": {"style": None, "text": {"required": True}}}
    assert merge(base, patch) == {
        "props": {"text": {"type": "string", "required": True}}
    }
    # The derived entry is evidence; applying policy never edits it.
    assert "style" in base["props"]


def test_a_non_object_patch_replaces_the_value() -> None:
    assert merge({"values": ["a"]}, {"values": ["b", "c"]}) == {"values": ["b", "c"]}


def test_diff_is_the_patch_merge_inverts() -> None:
    base = {"a": 1, "b": {"c": 2, "d": 3}, "gone": True}
    target = {"a": 1, "b": {"c": 5, "d": 3}, "new": [1]}
    patch = diff(base, target)
    assert patch == {"gone": None, "b": {"c": 5}, "new": [1]}
    assert merge(base, patch) == target


def test_policy_the_derivation_already_implies_is_reported() -> None:
    base = {"category": "input", "props": {"text": {"type": "string"}}}
    patch = {"category": "input", "props": {"text": {"type": "string"}}, "x": None}
    assert redundant(base, patch) == ["category", "props.text.type", "x"]


def test_every_held_component_says_why() -> None:
    for name, rule in load().components.items():
        if "manual" in rule:
            assert rule["manual"].strip(), name
            assert rule["entry"], name
        else:
            assert "decision" in rule, name


def test_the_lock_is_what_the_compiler_produces_from_the_pin() -> None:
    """The lock is generated, never edited: evidence plus policy reproduce it."""
    if os.environ.get("PYCOMPOSE_NATIVE_API_TESTS") != "1":
        pytest.skip("native CI runs the pinned artifact extraction")
    lock, report = generate(load())
    assert report.errors == []
    assert report.redundant == []
    assert LOCK.read_text(encoding="utf-8") == dumps(lock)


def _type(classifier: str, *arguments: KotlinType, **flags: object) -> KotlinType:
    return KotlinType(
        classifier=classifier,
        nullable=bool(flags.get("nullable")),
        annotations=tuple(flags.get("annotations", ())),
        arguments=tuple((None, argument) for argument in arguments),
    )


def test_a_signature_spells_types_as_kotlin_does() -> None:
    unit = _type("kotlin/Unit")
    scope = _type("androidx/compose/foundation/layout/RowScope")
    content = _type(
        "kotlin/Function1",
        scope,
        unit,
        annotations=(COMPOSABLE, EXTENSION),
    )
    assert type_text(content) == "@Composable foundation.layout.RowScope.() -> Unit"
    callback = _type("kotlin/Function1", _type("kotlin/String"), unit, nullable=True)
    assert type_text(callback) == "((String) -> Unit)?"
    listed = _type("kotlin/collections/List", _type("kotlin/Int"))
    assert type_text(listed) == "kotlin.collections.List<Int>"


def test_the_signature_file_is_what_the_pin_says() -> None:
    if os.environ.get("PYCOMPOSE_NATIVE_API_TESTS") != "1":
        pytest.skip("native CI runs the pinned artifact extraction")
    found = inventory(DUMP_DIR)
    path = ROOT / "schema/signatures" / f"{found.bom}.txt"
    assert path.read_text(encoding="utf-8") == render(found)
