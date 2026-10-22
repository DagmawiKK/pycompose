"""Python compositions observed through the public IR pipeline."""

import pytest

from pycompose import composable
from pycompose.core.expansion import ExpansionMemo
from pycompose.errors import IrValidationError
from pycompose.ir import emit_ir, to_dict, validate_ir
from pycompose.m3 import Column, Modifier, Scaffold, Text
from pycompose.state import State


def test_composable_expands_on_emission_with_scoped_identity() -> None:
    calls = []

    @composable
    def profile_header(*, name: str, modifier: Modifier | None = None):
        calls.append(name)
        return Column(
            id="content",
            modifier=modifier,
            children=(Text(id="name", text=name),),
        )

    first = profile_header(id="first", name="Ada", modifier=Modifier().padding(8))
    second = profile_header(id="second", name="Grace")
    state = State(root=Column(id="screen", children=(first, second)))
    assert calls == []
    candidate = emit_ir(state, "1.0.0")
    assert validate_ir(candidate).snapshot is candidate
    assert calls == ["Ada", "Grace"]
    assert to_dict(candidate)["root"] == {
        "id": "root",
        "type": "Column",
        "props": {},
        "children": [
            {
                "id": "root.first.content",
                "type": "Column",
                "props": {
                    "modifier": {"operations": [{"type": "padding", "value": 8}]}
                },
                "children": [
                    {
                        "id": "root.first.content.name",
                        "type": "Text",
                        "props": {"text": "Ada"},
                    }
                ],
            },
            {
                "id": "root.second.content",
                "type": "Column",
                "props": {},
                "children": [
                    {
                        "id": "root.second.content.name",
                        "type": "Text",
                        "props": {"text": "Grace"},
                    }
                ],
            },
        ],
    }


def test_python_declarations_cannot_cross_the_wire_unexpanded() -> None:
    from pycompose.errors import IrValidationError
    from pycompose.ir import to_json_bytes

    @composable
    def greeting():
        return Text(id="message", text="Hello")

    call = greeting(id="greeting")
    with pytest.raises(IrValidationError, match="expand"):
        to_json_bytes(call)


def test_named_content_callables_expand_on_the_worker() -> None:
    from pycompose.m3 import Scaffold

    calls = []

    def content():
        calls.append("content")
        return [Text(id="first", text="one"), Text(id="second", text="two")]

    root = Scaffold(id="screen", content=content)
    assert calls == []
    candidate = emit_ir(State(root=root), "1.0.0")
    assert calls == ["content"]
    assert validate_ir(candidate).snapshot is candidate
    assert [node.id for node in candidate.root.children] == [
        "root.content.first",
        "root.content.second",
    ]


def test_nested_compositions_are_stable_when_instances_reorder() -> None:
    from pycompose.ir import to_json_bytes

    @composable
    def label(*, text: str):
        return Text(id="text", text=text)

    @composable
    def row(*, text: str):
        return label(id="label", text=text)

    first = row(id="first", text="one")
    second = row(id="second", text="two")
    a = emit_ir(State(root=Column(id="screen", children=[first, second])), "1.0.0")
    b = emit_ir(State(root=Column(id="screen", children=[second, first])), "1.0.0")
    assert [node.id for node in a.root.children] == [
        "root.first.label.text",
        "root.second.label.text",
    ]
    assert b.root.children == tuple(reversed(a.root.children))
    assert to_json_bytes(a) == to_json_bytes(
        emit_ir(State(root=Column(id="screen", children=[first, second])), "1.0.0")
    )


def test_recursive_composition_has_definition_and_instance_context() -> None:
    from pycompose.composition import expand
    from pycompose.errors import IrValidationError

    @composable
    def recursive():
        return recursive(id="again")

    with pytest.raises(IrValidationError, match="recursive composable") as exc:
        expand(recursive(id="start"))
    assert "recursive" in exc.value.context["source"]
    assert "start" in str(exc.value.context["composition"])


def test_composable_detaches_mutable_prop_containers() -> None:
    from pycompose.composition import expand

    @composable
    def names(*, values):
        return Text(id="text", text=", ".join(values))

    values = ["Ada"]
    call = names(id="names", values=values)
    values.append("Grace")
    assert expand(call).props["text"] == "Ada"


def test_invalid_output_does_not_replace_the_last_good_bridge_snapshot() -> None:
    from dataclasses import replace

    from pycompose.bridge import BridgeSurface
    from pycompose.state import Actions, Store

    @composable
    def broken():
        return None

    initial = State(root=Text(id="message", text="Hello"))
    store = Store(initial)
    actions = Actions()
    actions.register(
        "increment", lambda state, _: replace(state, root=broken(id="broken"))
    )
    bridge = BridgeSurface(store, actions)
    snapshot = bridge.expose_latest_snapshot()
    bridge.accept_action('{"actionId":"increment","payload":{"by":1}}')
    assert bridge.expose_latest_snapshot() == snapshot
    assert store.value is initial


def test_modifiers_are_forwarded_once_without_altering_internal_order() -> None:
    from pycompose.composition import expand

    @composable
    def padded(*, modifier: Modifier):
        return Text(id="text", text="Hello", modifier=modifier.padding(4))

    result = expand(padded(id="padded", modifier=Modifier().padding(8)))
    assert result.props.to_wire()["modifier"] == {
        "operations": [
            {"type": "padding", "value": 8},
            {"type": "padding", "value": 4},
        ],
    }


def test_recursive_composition_can_make_progress_with_explicit_inputs() -> None:
    @composable
    def nested(*, remaining: int):
        if remaining == 0:
            return Text(id="leaf", text="done")
        return Column(
            id="branch", children=[nested(id="next", remaining=remaining - 1)]
        )

    snapshot = emit_ir(State(root=nested(id="tree", remaining=1500)), "1.0.0")
    assert validate_ir(snapshot).snapshot is snapshot
    node = snapshot.root
    while node.children:
        node = node.children[0]
    assert node.props["text"] == "done"


def test_a_composable_fills_a_declared_slot() -> None:
    """A named slot takes nodes, and a composable instance is one.

    The slot is the parent's structural fact, so it has to outlive expansion:
    the deferred call is replaced by what it builds, carrying the slot with it
    and stamping the instance key onto the built root.
    """

    @composable
    def header(*, text: str):
        return Text(id="title", text=text)

    snapshot = emit_ir(
        State(
            root=Scaffold(
                id="screen",
                top_bar=header(id="bar", text="Notes"),
                content=Column(id="body", children=(Text(id="line", text="hello"),)),
            )
        ),
        "1.0.0",
    )
    assert validate_ir(snapshot).snapshot is snapshot
    root = to_dict(snapshot)["root"]
    assert [(child["type"], child.get("slot")) for child in root["children"]] == [
        ("Column", None),
        ("Text", "topBar"),
    ]
    title = root["children"][1]
    assert title["id"] == "root.bar.title"
    assert title["props"]["text"] == "Notes"


def _rows(names: list[str], render: object) -> State:
    return State(
        root=Column(
            id="screen",
            children=tuple(render(id=f"row{i}", name=n) for i, n in enumerate(names)),  # type: ignore[operator]
        )
    )


def test_a_memo_reruns_only_the_composables_whose_inputs_changed() -> None:
    calls: list[str] = []

    @composable
    def row(*, name: str):
        calls.append(name)
        return Text(id="name", text=name)

    memo = ExpansionMemo()
    emit_ir(_rows(["Ada", "Grace"], row), "1.0.0", memo)
    reused = emit_ir(_rows(["Ada", "Hopper"], row), "1.0.0", memo)

    assert calls == ["Ada", "Grace", "Hopper"]
    fresh = emit_ir(_rows(["Ada", "Hopper"], row), "1.0.0")
    assert to_dict(reused) == to_dict(fresh)


def test_verification_catches_a_composable_reading_outside_its_inputs() -> None:
    outside = ["Ada"]

    @composable
    def row(*, name: str):
        return Text(id="name", text=f"{name} {outside[0]}")

    memo = ExpansionMemo(verify_every=1)
    emit_ir(_rows(["x"], row), "1.0.0", memo)
    outside[0] = "Grace"
    with pytest.raises(IrValidationError, match="outside its arguments"):
        emit_ir(_rows(["x"], row), "1.0.0", memo)
