"""Declared payload contracts at the public action-dispatch seam."""

from dataclasses import replace
from typing import Literal, NotRequired, TypedDict

import pytest

from pycompose import action
from pycompose.core import Node
from pycompose.errors import IrValidationError
from pycompose.state import Actions, State


class ResultPayload(TypedDict):
    result_text: str


@action
def accept_result(state: State, payload: ResultPayload) -> State:
    return replace(state, version=len(payload.get("result_text", "")))


def test_qualified_dispatch_rejects_missing_required_payload_fields() -> None:
    actions = Actions(accept_result)
    state = State(root=Node(id="root", type="Text"))

    with pytest.raises(IrValidationError, match="missing app payload field"):
        actions.dispatch(accept_result.name, state, {})


def test_alias_dispatch_rejects_invalid_declared_field_types() -> None:
    actions = Actions(accept_result)
    state = State(root=Node(id="root", type="Text"))

    with pytest.raises(IrValidationError, match="invalid app payload field"):
        actions.dispatch("acceptResult", state, {"resultText": 3})


@pytest.mark.parametrize("action_id", [accept_result.name, "acceptResult"])
def test_omitted_payload_still_enforces_required_fields(action_id: str) -> None:
    with pytest.raises(IrValidationError, match="missing app payload field"):
        Actions(accept_result).dispatch(
            action_id, State(root=Node(id="root", type="Text"))
        )


@pytest.mark.parametrize("payload", [[], "text", 3, False])
@pytest.mark.parametrize("action_id", [accept_result.name, "acceptResult"])
def test_declared_actions_reject_non_object_payloads(
    action_id: str, payload: object
) -> None:
    with pytest.raises(IrValidationError, match="payload must be an object"):
        Actions(accept_result).dispatch(
            action_id, State(root=Node(id="root", type="Text")), payload
        )


@pytest.mark.parametrize("action_id", [accept_result.name, "acceptResult"])
def test_wire_and_python_names_cannot_overwrite_each_other(action_id: str) -> None:
    with pytest.raises(IrValidationError, match="collid"):
        Actions(accept_result).dispatch(
            action_id,
            State(root=Node(id="root", type="Text")),
            {"resultText": 3, "result_text": "valid"},
        )


class OptionsPayload(TypedDict, total=False):
    count: int
    score: float
    enabled: bool
    mode: Literal["fast", "slow"]
    label: NotRequired[str]


@action
def accept_options(state: State, payload: OptionsPayload) -> State:
    return replace(state, version=payload.get("count", 1))


@pytest.mark.parametrize("action_id", [accept_options.name, "acceptOptions"])
@pytest.mark.parametrize(
    "payload",
    [
        {"unknown": "value"},
        {"count": True},
        {"score": False},
        {"score": float("nan")},
        {"score": float("inf")},
        {"enabled": 1},
        {"mode": "other"},
        {"label": 2},
    ],
)
def test_alias_and_qualified_dispatch_enforce_optional_field_contracts(
    action_id: str, payload: object
) -> None:
    with pytest.raises(IrValidationError):
        Actions(accept_options).dispatch(
            action_id, State(root=Node(id="root", type="Text")), payload
        )


@pytest.mark.parametrize("action_id", [accept_result.name, "acceptResult"])
@pytest.mark.parametrize("field", ["resultText", "result_text"])
def test_valid_payloads_translate_identically(action_id: str, field: str) -> None:
    state = State(root=Node(id="root", type="Text"))
    assert (
        Actions(accept_result).dispatch(action_id, state, {field: "done"}).version == 4
    )


@pytest.mark.parametrize("payload", [None, {}, {"count": 3, "score": 0.5}])
def test_optional_payload_fields_may_be_omitted(payload: object) -> None:
    state = State(root=Node(id="root", type="Text"))
    result = Actions(accept_options).dispatch("acceptOptions", state, payload)
    assert result.version == (3 if payload else 1)


def test_bindings_remain_partial_until_dispatch() -> None:
    actions = Actions(accept_result)
    binding = accept_result.bind(id="result")
    state = State(root=Node(id="root", type="Text"))

    assert (
        actions.dispatch_binding(binding.spec, state, {"resultText": "done"}).version
        == 4
    )
    with pytest.raises(IrValidationError, match="missing app payload field"):
        actions.dispatch_binding(binding.spec, state, {})


def test_fixed_binding_fields_are_preserved_and_cannot_be_overridden() -> None:
    actions = Actions(accept_result)
    binding = accept_result.bind(id="result", result_text="done")
    state = State(root=Node(id="root", type="Text"))

    assert actions.dispatch_binding(binding.spec, state, {}).version == 4
    with pytest.raises(IrValidationError, match="unknown app payload fields"):
        actions.dispatch_binding(binding.spec, state, {"resultText": "replacement"})
