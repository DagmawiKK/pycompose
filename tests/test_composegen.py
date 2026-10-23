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
    # Determinism: a second clean run is byte-identical.
    assert dumps(generate(load())[0]) == dumps(lock)


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


@pytest.mark.parametrize(
    ("declared", "rule"),
    [
        (
            _type("kotlin/Function0", _type("kotlin/Float")),
            {"policy": "provider", "wireType": "float"},
        ),
        (
            _type("androidx/compose/material3/SearchBarState"),
            {"policy": "holder", "kind": "search"},
        ),
        (
            _type("androidx/compose/ui/graphics/painter/Painter"),
            {
                "policy": "resource",
                "decode": "resourceImage",
                "values": ["drawable", "asset"],
            },
        ),
    ],
)
def test_the_host_fills_late_reads_holders_and_resources(
    declared: KotlinType, rule: dict[str, object]
) -> None:
    """The type alone decides: no component names its own exception."""
    from tools.schema.classpath_types import Parameter
    from tools.schema.components import _binding_rule

    assert _binding_rule(Parameter("p", declared, False, None), {}, {}) == rule


def test_a_nullable_late_read_is_refused() -> None:
    from tools.schema.classpath_types import Parameter
    from tools.schema.components import _binding_rule

    provider = _type("kotlin/Function0", _type("kotlin/Float", nullable=True))
    with pytest.raises(ValueError, match="provider/predicate protocol"):
        _binding_rule(Parameter("p", provider, False, None), {}, {})


def _plan(**parameters: dict[str, object]) -> dict[str, object]:
    return {
        "parameters": {
            name: {"type": {"classifier": "kotlin/Unit"}, "required": False, **spec}
            for name, spec in parameters.items()
        }
    }


def test_flatten_turns_the_primary_content_into_text() -> None:
    from tools.composegen.rules import reshape

    entry = {"props": {"modifier": {"type": "modifier"}}, "children": {"allowed": True}}
    plan = _plan(content={"policy": "slot", "required": True})
    shaped = reshape("Button", entry, {"flatten": ["content"]}, plan)
    assert shaped["children"] == {"allowed": False}
    assert shaped["props"]["text"] == {
        "type": "string",
        "required": True,
        "content": {"composable": "Text"},
    }
    # Compose has no `text` parameter, so the prop is recorded as invented.
    assert shaped["reshaped"] == ["text"]
    assert "text" not in entry["props"]


def test_flatten_keeps_a_named_slot_under_its_native_name() -> None:
    from tools.composegen.rules import reshape

    entry = {
        "props": {},
        "children": {"allowed": False},
        "slots": {"label": {"native": "label", "nullable": True}},
    }
    plan = _plan(label={"policy": "slot"})
    shaped = reshape("TextField", entry, {"flatten": ["label"]}, plan)
    assert "slots" not in shaped
    assert shaped["props"]["label"] == {
        "type": "string",
        "content": {"composable": "Text", "parameter": "label"},
    }
    assert "reshaped" not in shaped


def test_observe_reports_every_interaction_the_source_emits() -> None:
    from tools.composegen.rules import INTERACTION_SOURCE, reshape

    plan = _plan(source={"policy": "omit", "type": {"classifier": INTERACTION_SOURCE}})
    shaped = reshape("Chip", {"props": {}}, {"observe": True}, plan)
    assert shaped["interaction"] == {
        "native": "source",
        "observations": {"press": "onPress", "focus": "onFocus", "hover": "onHover"},
    }
    assert shaped["props"]["onFocus"] == {
        "type": "actionId",
        "payload": [{"name": "focused", "type": "boolean"}],
    }
    assert shaped["reshaped"] == ["onPress", "onFocus", "onHover"]


def test_a_shape_the_pin_cannot_carry_is_refused() -> None:
    from tools.composegen.rules import reshape
    from tools.schema.candidate_props import CandidateError

    with pytest.raises(CandidateError, match="no slot"):
        reshape("Text", {"props": {}}, {"flatten": ["text"]}, _plan())
    with pytest.raises(CandidateError, match="interaction source"):
        reshape("Text", {"props": {}}, {"observe": True}, _plan())


def test_a_deprecated_overload_never_competes_for_the_name() -> None:
    from tools.schema.entry_candidates import select

    def candidate(jvm: str, **annotations: object) -> dict[str, object]:
        return {
            "name": "Dialog",
            "surface": "component",
            "status": "call-plan",
            "annotations": annotations,
            "source": {
                "artifact": "a",
                "owner": "o",
                "jvmName": jvm,
                "descriptor": "()V",
            },
        }

    plans = {
        "candidates": [candidate("old", **{"kotlin/Deprecated": {}}), candidate("new")]
    }
    with pytest.raises(Exception, match="plan source is not pinned"):
        # One plan is left, so selection proceeds to the pin lookup.
        select(plans, _no_declarations(), "Dialog")


def _no_declarations() -> object:
    class Empty:
        declarations = ()

    return Empty()
