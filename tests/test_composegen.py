"""The component compiler: policy overlay semantics and lock reproduction."""

from __future__ import annotations

import os

import pytest

from tools.composegen.lock import LOCK, dumps, generate
from tools.composegen.policy import diff, load, merge, redundant


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
