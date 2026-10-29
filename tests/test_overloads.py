"""Overloads behind one Python name: dispatch, proof, naming and slicing."""

from __future__ import annotations

from typing import Any, NoReturn

import pytest
from pycompose_codegen.emit.overloads import ambiguous, keywords, validate

from pycompose.app import Intent
from pycompose.state import State


def _entry(*required: str, optional: tuple[str, ...] = (), children: bool = False):
    props: dict[str, Any] = {"modifier": {"type": "modifier"}}
    props |= {name: {"type": "string", "required": True} for name in required}
    props |= {name: {"type": "string"} for name in optional}
    return {"props": props, "children": {"allowed": children}}


def _die(message: str) -> NoReturn:
    raise ValueError(message)


def test_keywords_leave_out_what_every_component_takes() -> None:
    entry = _entry("onClick", optional=("enabled",), children=True)
    assert keywords(entry) == (
        frozenset({"on_click"}),
        frozenset({"on_click", "enabled", "content"}),
    )


def test_keywords_tell_overloads_apart_only_without_a_shared_call() -> None:
    clickable = _entry("onClick", optional=("enabled",), children=True)
    plain = _entry(children=True)
    # Every plain call lacks on_click, which the clickable one requires.
    assert not ambiguous(clickable, plain)
    # Two overloads both satisfied by `selected` and `on_click` share a call.
    assert ambiguous(_entry("selected", "onClick"), _entry("selected", "onClick"))


def test_a_group_keywords_cannot_dispatch_is_refused() -> None:
    components = {
        "Tab": _entry("selected", "onClick"),
        "TabContent": {**_entry("selected", "onClick"), "overloadOf": "Tab"},
    }
    with pytest.raises(ValueError, match="cannot tell 'Tab' from 'TabContent'"):
        validate(components, _die)
    orphan = {"CardPlain": {**_entry(), "overloadOf": "Card"}}
    with pytest.raises(ValueError, match="names no primary"):
        validate(orphan, _die)


def _plan(*parameters: tuple[str, str, bool]) -> dict[str, Any]:
    return {
        "parameters": {
            name: {
                "type": {"classifier": classifier},
                "required": required,
                "policy": "x",
            }
            for name, classifier, required in parameters
        }
    }


def test_an_overload_is_named_after_what_sets_it_apart() -> None:
    from pycompose_codegen.derive.overloads import suffix

    content = ("content", "kotlin/Function3", True)
    clickable = _plan(("onClick", "kotlin/Function0", True), content)
    assert suffix(_plan(content), clickable) == "WithoutOnClick"
    plain = _plan(content)
    selected = _plan(("selected", "kotlin/Boolean", True), content)
    assert suffix(selected, plain) == "Selected"
    text = _plan(("text", "kotlin/String", True))
    annotated = _plan(("text", "androidx/compose/ui/text/AnnotatedString", True))
    assert suffix(annotated, text) == "AnnotatedString"
    assert suffix(text, text) is None


def test_the_keywords_a_call_passes_choose_the_overload() -> None:
    from pycompose.contract.catalog import SCHEMA_VERSION
    from pycompose.material3 import Card, CardWithoutOnClick, Text
    from pycompose.wire import emit_ir, to_json

    class OpenNote(Intent):
        pass

    clickable = Card(Text(text="Open"), on_click=OpenNote())
    plain = Card(Text(text="Static"))
    assert type(clickable) is Card
    assert type(plain) is CardWithoutOnClick
    # Every overload is still the name it was reached through.
    assert isinstance(plain, Card)
    wire = to_json(emit_ir(State(root=plain), SCHEMA_VERSION))
    assert '"type":"CardWithoutOnClick"' in wire.replace(" ", "")
    with pytest.raises(TypeError):
        Card(Text(text="x"), nope=1)  # type: ignore[call-overload]


def test_an_app_slice_carries_the_overloads_of_what_it_uses() -> None:
    from pycompose_codegen.emit.app_slice import slice_registry

    registry = {
        "components": {
            "Card": _entry("onClick"),
            "CardWithoutOnClick": {**_entry(), "overloadOf": "Card"},
            "Text": _entry("text"),
        },
        "valueTypes": {},
    }
    assert set(slice_registry(registry, {"Card"})["components"]) == {
        "Card",
        "CardWithoutOnClick",
    }
