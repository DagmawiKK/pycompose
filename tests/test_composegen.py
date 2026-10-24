"""The component compiler: policy overlay semantics and lock reproduction."""

from __future__ import annotations

import os

import pytest

from pycompose.compiler.classpath_dump import DUMP_DIR, inventory
from pycompose.compiler.classpath_types import COMPOSABLE, EXTENSION, KotlinType
from pycompose.compiler.lock import LOCK, ROOT, dumps, generate
from pycompose.compiler.policy import diff, load, merge, redundant
from pycompose.compiler.signatures import render, type_text


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
    # Policy liveness: no redundant patch entry and no stale hold.
    assert report.errors == []
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
    from pycompose.compiler.classpath_types import Parameter
    from pycompose.compiler.components import _binding_rule

    assert _binding_rule(Parameter("p", declared, False, None), {}, {}) == rule


def test_a_nullable_late_read_is_refused() -> None:
    from pycompose.compiler.classpath_types import Parameter
    from pycompose.compiler.components import _binding_rule

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
    from pycompose.compiler.rules import reshape

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
    from pycompose.compiler.rules import reshape

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
    from pycompose.compiler.rules import INTERACTION_SOURCE, reshape

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
    from pycompose.compiler.candidate_props import CandidateError
    from pycompose.compiler.rules import reshape

    with pytest.raises(CandidateError, match="no slot"):
        reshape("Text", {"props": {}}, {"flatten": ["text"]}, _plan())
    with pytest.raises(CandidateError, match="interaction source"):
        reshape("Text", {"props": {}}, {"observe": True}, _plan())


def test_a_deprecated_overload_never_competes_for_the_name() -> None:
    from pycompose.compiler.entry_candidates import select

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


def test_a_hold_is_stale_only_when_its_own_overload_derives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pycompose.compiler import lock

    source = {
        "artifact": "a",
        "owner": "o",
        "name": "Slider",
        "jvmName": "S",
        "descriptor": "()V",
    }
    entry = {"category": "input", "stability": "stable", "source": source}
    monkeypatch.setattr(lock, "planned", lambda *_: {"source": source})
    assert lock._derives("Slider", entry, {}, None, {})
    other = {**source, "jvmName": "Other"}
    monkeypatch.setattr(lock, "planned", lambda *_: {"source": other})
    assert not lock._derives("Slider", entry, {}, None, {})


def test_a_bound_holder_takes_its_family_projection() -> None:
    from pycompose.compiler.rules import reshape

    entry = {"props": {}, "state": {"native": "drawerState", "kind": "drawer"}}
    shaped = reshape("Drawer", entry, {}, _plan())
    assert shaped["state"] == {
        "native": "drawerState",
        "kind": "drawer",
        "value": "open",
        "report": "onOpenChange",
    }
    assert shaped["props"]["onOpenChange"] == {
        "type": "actionId",
        "payload": [{"name": "open", "type": "boolean"}],
    }
    assert shaped["reshaped"] == ["open", "onOpenChange"]


def test_a_family_with_held_props_projects_them_after_its_report() -> None:
    from pycompose.compiler.rules import reshape

    entry = {"props": {}, "state": {"native": "state", "kind": "slider"}}
    shaped = reshape("Slider", entry, {}, _plan())
    assert shaped["reshaped"] == [
        "value",
        "onValueChangeFinished",
        "valueRange",
        "steps",
    ]
    assert shaped["props"]["valueRange"]["valueType"] == "Range"


def test_a_declined_holder_is_not_bound() -> None:
    from pycompose.compiler.rules import reshape

    entry = {"props": {}, "state": {"native": "scrollState", "kind": "scroll"}}
    shaped = reshape("DropdownMenu", entry, {"holder": False}, _plan())
    assert "state" not in shaped
    assert shaped["props"] == {}


def test_codegen_reads_held_props_from_the_families() -> None:
    from pycompose.schema.codegen.adapter_helpers import STATE_CONSTRUCTOR_PROPS
    from pycompose.schema.codegen.state_families import STATE_FAMILIES

    assert STATE_CONSTRUCTOR_PROPS["slider"] == ("valueRange", "steps")
    assert set(STATE_CONSTRUCTOR_PROPS) == {
        kind for kind, family in STATE_FAMILIES.items() if family.held
    }


def _overload(receiver: str | None = None, **parameters: tuple[bool, bool]) -> dict:
    """A plan whose parameters are (forwarded, has_default), all of one type."""
    return {
        "receiver": {"classifier": receiver} if receiver else None,
        "parameters": {
            name: {
                "policy": "scalar" if forwarded else "omit",
                "required": not has_default,
                "hasDefault": has_default,
                "type": {
                    "classifier": "kotlin/Int",
                    "nullable": False,
                    "annotations": [],
                    "arguments": [],
                },
            }
            for name, (forwarded, has_default) in parameters.items()
        },
    }


def test_the_overload_leaving_fewer_defaults_wins_a_tie() -> None:
    """Kotlin spec 11.6: equally specific, fewer unspecified defaults is chosen."""
    from pycompose.compiler.components import _competing

    current = _overload(items=(True, True), spacing=(False, True))
    deprecated = _overload(
        items=(True, True), spacing=(False, True), overflow=(False, True)
    )
    assert not _competing(current, deprecated)
    assert _competing(deprecated, current)


def test_an_extension_on_a_scope_never_competes_with_a_top_level_overload() -> None:
    from pycompose.compiler.components import _competing

    top = _overload(visible=(True, False))
    scoped = _overload(
        "androidx/compose/foundation/layout/RowScope", visible=(True, False)
    )
    assert not _competing(top, scoped)
    assert not _competing(scoped, top)


def test_a_transient_holder_takes_its_family_projection() -> None:
    from pycompose.compiler.rules import reshape

    entry = {"props": {}, "transient": {"kind": "snackbar", "native": "hostState"}}
    shaped = reshape("SnackbarHost", entry, {}, _plan())
    assert shaped["transient"] == {
        "kind": "snackbar",
        "native": "hostState",
        "serial": "serial",
        "occurrence": "onDismiss",
    }
    assert shaped["reshaped"] == ["message", "actionLabel", "serial", "onDismiss"]


def test_the_host_builds_a_value_from_a_prop_it_names() -> None:
    from pycompose.compiler.classpath_types import Parameter
    from pycompose.compiler.components import _binding_rule

    provider = _type("androidx/compose/ui/window/PopupPositionProvider")
    rule = _binding_rule(Parameter("positionProvider", provider, False, None), {}, {})
    assert rule["policy"] == "hostValue"
    assert rule["prop"] == "position"
    assert rule["spec"]["decode"] == "tooltipPosition"


def test_an_overload_with_several_holders_binds_the_one_named() -> None:
    from pycompose.compiler.candidate_props import CandidateError
    from pycompose.compiler.rules import reshape

    holders = [
        {"native": "state", "kind": "textInput"},
        {"native": "scrollState", "kind": "scroll"},
    ]
    with pytest.raises(CandidateError, match="name the holder it binds"):
        reshape("Field", {"props": {}, "holders": list(holders)}, {}, _plan())
    chosen = reshape(
        "Field", {"props": {}, "holders": list(holders)}, {"holder": "state"}, _plan()
    )
    assert chosen["state"]["kind"] == "textInput"
    assert "holders" not in chosen
    declined = reshape(
        "Field", {"props": {}, "holders": list(holders)}, {"holder": False}, _plan()
    )
    assert "state" not in declined


def test_an_interaction_source_is_observed_unless_policy_declines() -> None:
    from pycompose.compiler.rules import INTERACTION_SOURCE, reshape

    plan = _plan(source={"policy": "omit", "type": {"classifier": INTERACTION_SOURCE}})
    assert "interaction" in reshape("Chip", {"props": {}}, {}, plan)
    declined = reshape("Field", {"props": {}}, {"observe": False}, plan)
    assert "interaction" not in declined
    assert "onPress" not in declined["props"]


def _candidate(name: str, artifact: str, **fields: object) -> dict[str, object]:
    return {
        "name": name,
        "surface": "component",
        "status": "call-plan",
        "annotations": {},
        "optIn": [],
        "parameters": {},
        **fields,
        "source": {
            "artifact": f"{artifact}:x:1",
            "jvmName": name,
            "descriptor": fields.get("descriptor", ""),
        },
    }


def test_a_component_no_policy_names_is_promoted_with_derived_decisions() -> None:
    from pycompose.compiler.lock import promotable

    foundation, material = "androidx.compose.foundation", "androidx.compose.material3"
    plans = {
        "candidates": [
            _candidate("Covered", material),
            _candidate("Plain", foundation),
            _candidate("Opted", material, optIn=["Experimental"]),
            _candidate("Old", material, annotations={"kotlin/Deprecated": {}}),
            _candidate("Two", material, parameters={"a": {}}, descriptor="(A)"),
            _candidate(
                "Two", material, parameters={"a": {}, "b": {}}, descriptor="(AB)"
            ),
        ]
    }
    decisions = promotable(plans, {"Covered"})
    # Already covered, or deprecated in every overload: never promoted.
    assert sorted(decisions) == ["Opted", "Plain", "Two"]
    assert decisions["Plain"] == {"category": "foundation", "stability": "stable"}
    assert decisions["Opted"]["stability"] == "experimental"
    # Of several overloads, the one taking the most parameters is the primary.
    assert decisions["Two"]["identity"].endswith("Two(AB)")


def test_a_family_sharing_its_owner_needs_a_hand_written_adapter() -> None:
    from pycompose.compiler.rules import reshape

    entry = {"props": {}, "state": {"native": "state", "kind": "search"}}
    assert reshape("Bar", entry, {}, _plan())["adapter"] == "manual"
