"""Builder scopes whose members are items, and holders a slot is handed."""

from types import SimpleNamespace
from typing import Any

import pytest
from pycompose_codegen.derive.candidate_props import CandidateError
from pycompose_codegen.derive.item_shape import place_members
from pycompose_codegen.derive.members import (
    drop_itemless,
    handed_holders,
    item_name,
    member_scopes,
)
from pycompose_codegen.derive.slots import builder_rule, slot_rule

PACKAGE = "androidx.compose.material3"
SCOPE = "androidx/compose/material3/AppBarScope"
ROW_SCOPE = "androidx/compose/material3/AppBarRowScope"
MENU = "androidx.compose.material3.AppBarMenuState"
COMPOSABLE = "androidx/compose/runtime/Composable"
EXTENSION = "kotlin/ExtensionFunctionType"
HANDED = {
    "holder": MENU,
    "value": "isExpanded",
    "drives": {"true": "show", "false": "dismiss"},
}


def _type(classifier: str, *arguments: Any, annotations: tuple = ()) -> Any:
    return SimpleNamespace(
        classifier=classifier,
        nullable=False,
        suspend=False,
        annotations=annotations,
        arguments=tuple(("INVARIANT", argument) for argument in arguments),
    )


UNIT = _type("kotlin/Unit")


def _member(owner: str, name: str, kind: str = "function", **fields: Any) -> Any:
    receiver = _type(owner.replace(".", "/"))
    return SimpleNamespace(
        **{
            "owner": owner,
            "name": name,
            "jvm_name": name,
            "jvm_descriptor": "()V",
            "disposition": "support",
            "composable": False,
            "dispatch_receiver": receiver,
            "receiver": None,
            "return_type": UNIT,
            "parameters": (),
            "document": {"declarationKind": kind},
            **fields,
        }
    )


def _found(*declarations: Any, ui: tuple = (), classes: tuple = ()) -> Any:
    return SimpleNamespace(declarations=declarations, ui=ui, classes=classes)


def test_a_builder_scope_takes_the_items_its_supertypes_declare() -> None:
    builder = _type(
        "kotlin/Function1", _type(ROW_SCOPE), UNIT, annotations=(EXTENSION,)
    )
    bar = SimpleNamespace(parameters=(SimpleNamespace(type=builder),))
    found = _found(
        _member(SCOPE.replace("/", "."), "clickableItem"),
        ui=(bar,),
        classes=(
            SimpleNamespace(
                classifier=ROW_SCOPE.replace("/", "."), supertypes=(SCOPE,)
            ),
        ),
    )
    assert member_scopes(found) == {ROW_SCOPE: {"kind": "members", "items": [SCOPE]}}  # type: ignore[arg-type]


def test_a_composable_lambda_is_a_slot_never_a_builder() -> None:
    slot = _type(
        "kotlin/Function1", _type(ROW_SCOPE), UNIT, annotations=(EXTENSION, COMPOSABLE)
    )
    found = _found(
        _member(ROW_SCOPE.replace("/", "."), "clickableItem"),
        ui=(SimpleNamespace(parameters=(SimpleNamespace(type=slot),)),),
    )
    assert member_scopes(found) == {}  # type: ignore[arg-type]


def test_an_item_is_named_by_its_scope_unless_a_composable_has_the_name() -> None:
    clickable = _member(SCOPE.replace("/", "."), "clickableItem")
    item = _member("pkg.NavigationSuiteScope", "item")
    assert item_name(clickable, frozenset()) == "AppBarClickableItem"  # type: ignore[arg-type]
    taken = frozenset({"NavigationSuiteItem"})
    assert item_name(item, taken) == "NavigationSuiteScopeItem"  # type: ignore[arg-type]


def _menu(*members: str) -> tuple[Any, dict[tuple[str, str, str], dict[str, Any]]]:
    read = _member(MENU, "isExpanded", "property", return_type=_type("kotlin/Boolean"))
    bare = [_member(MENU, name) for name in members]
    drives = {
        (MENU, "show", "()V"): {
            "kind": "assigns",
            "property": "isExpanded",
            "value": True,
        },
        (MENU, "dismiss", "()V"): {
            "kind": "assigns",
            "property": "isExpanded",
            "value": False,
        },
    }
    return _found(read, *bare), drives


def test_members_setting_both_values_of_one_property_hand_it_over() -> None:
    found, drives = _menu("show", "dismiss")
    assert handed_holders(found, drives) == {  # type: ignore[arg-type]
        MENU.replace(".", "/"): {"kind": "handed", **HANDED}
    }


def test_a_bare_member_with_no_evidence_refuses_the_holder() -> None:
    found, drives = _menu("show", "dismiss", "toggle")
    assert handed_holders(found, drives) == {}  # type: ignore[arg-type]


def test_one_value_set_by_nothing_refuses_the_holder() -> None:
    found, drives = _menu("show")
    del drives[(MENU, "dismiss", "()V")]
    assert handed_holders(found, drives) == {}  # type: ignore[arg-type]


def test_rules_mark_members_builders_and_handed_slots() -> None:
    holders = {
        ROW_SCOPE: {"kind": "members", "items": [SCOPE]},
        MENU.replace(".", "/"): {"kind": "handed", **HANDED},
    }
    builder = _type(
        "kotlin/Function1", _type(ROW_SCOPE), UNIT, annotations=(EXTENSION,)
    )
    assert builder_rule(builder, holders) == {  # type: ignore[arg-type]
        "policy": "slot",
        "receiver": ROW_SCOPE,
        "kind": "members",
        "applies": [SCOPE.replace("/", ".")],
    }
    slot = _type(
        "kotlin/Function1",
        _type(MENU.replace(".", "/")),
        UNIT,
        annotations=(COMPOSABLE,),
    )
    assert slot_rule(slot, holders)["handed"] == HANDED  # type: ignore[arg-type]


def test_an_unknown_builder_scope_is_refused() -> None:
    builder = _type(
        "kotlin/Function1", _type("pkg/Other"), UNIT, annotations=(EXTENSION,)
    )
    with pytest.raises(ValueError, match="builder scope needs a native protocol"):
        builder_rule(builder, {})  # type: ignore[arg-type]


def _plan() -> dict[str, Any]:
    return {
        "parameters": {
            "overflowIndicator": {"policy": "slot", "handed": HANDED},
            "content": {
                "policy": "slot",
                "kind": "members",
                "applies": [SCOPE.replace("/", ".")],
            },
        }
    }


def test_a_handed_holder_becomes_a_value_and_its_report() -> None:
    props: dict[str, Any] = {}
    children = {"allowed": True, "kind": "content"}
    slots: dict[str, Any] = {"overflowIndicator": {"native": "overflowIndicator"}}
    place_members("AppBarRow", _plan(), props, children, slots)
    assert children["kind"] == "members"
    assert children["applies"] == [SCOPE.replace("/", ".")]
    assert slots["overflowIndicator"]["handed"] == HANDED
    assert props == {
        "isExpanded": {"type": "boolean"},
        "onIsExpandedChange": {
            "type": "actionId",
            "payload": [{"name": "isExpanded", "type": "boolean"}],
        },
    }


def test_a_handed_value_colliding_with_a_prop_is_refused() -> None:
    props = {"isExpanded": {"type": "boolean"}}
    slots: dict[str, Any] = {"overflowIndicator": {"native": "overflowIndicator"}}
    with pytest.raises(CandidateError, match="already a prop"):
        place_members("AppBarRow", _plan(), props, {"allowed": True}, slots)


def test_a_builder_no_item_fills_is_dropped_with_its_reason() -> None:
    builder = {"kind": "members", "provides": f"{PACKAGE}.AppBarRowScope"}
    components = {
        "AppBarRow": {"children": {**builder, "applies": [f"{PACKAGE}.AppBarScope"]}},
        "Surface": {"children": {**builder, "applies": ["pkg.SurfaceScope"]}},
        "AppBarClickableItem": {"item": True, "scope": f"{PACKAGE}.AppBarScope"},
    }
    dropped = drop_itemless(components)
    assert dropped == {"Surface": f"no item component fills {PACKAGE}.AppBarRowScope"}
    assert set(components) == {"AppBarRow", "AppBarClickableItem"}
