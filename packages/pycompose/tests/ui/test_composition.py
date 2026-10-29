"""Python compositions observed through the public IR pipeline."""

import pytest
from readable import readable_reuse, rename

from pycompose import composable
from pycompose.core.expansion import ExpansionMemo
from pycompose.core.reuse import Reuse
from pycompose.errors import IrValidationError
from pycompose.foundation import Column
from pycompose.material3 import Scaffold, Text
from pycompose.state import State
from pycompose.ui import Modifier
from pycompose.wire import emit_ir, to_dict, validate_ir


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
    reuse = readable_reuse()
    candidate = emit_ir(state, "1.0.0", reuse)
    assert validate_ir(candidate).snapshot is candidate
    assert calls == ["Ada", "Grace"]
    assert rename(to_dict(candidate), reuse)["root"] == {
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
    from pycompose.wire import to_json_bytes

    @composable
    def greeting():
        return Text(id="message", text="Hello")

    call = greeting(id="greeting")
    with pytest.raises(IrValidationError, match="expand"):
        to_json_bytes(call)


def test_named_content_callables_expand_on_the_worker() -> None:
    from pycompose.material3 import Scaffold

    calls = []

    def content():
        calls.append("content")
        return [Text(id="first", text="one"), Text(id="second", text="two")]

    root = Scaffold(id="screen", content=content)
    assert calls == []
    reuse = readable_reuse()
    candidate = emit_ir(State(root=root), "1.0.0", reuse)
    assert calls == ["content"]
    assert validate_ir(candidate).snapshot is candidate
    assert [n["id"] for n in rename(to_dict(candidate), reuse)["root"]["children"]] == [
        "root.content.first",
        "root.content.second",
    ]


def test_nested_compositions_are_stable_when_instances_reorder() -> None:
    from pycompose.wire import to_json_bytes

    @composable
    def label(*, text: str):
        return Text(id="text", text=text)

    @composable
    def row(*, text: str):
        return label(id="label", text=text)

    first = row(id="first", text="one")
    second = row(id="second", text="two")
    # One session: its names follow each identity across the reorder.
    reuse = readable_reuse()
    a = emit_ir(
        State(root=Column(id="screen", children=[first, second])), "1.0.0", reuse
    )
    b = emit_ir(
        State(root=Column(id="screen", children=[second, first])), "1.0.0", reuse
    )
    assert [n["id"] for n in rename(to_dict(a), reuse)["root"]["children"]] == [
        "root.first.label.text",
        "root.second.label.text",
    ]
    assert b.root.children == tuple(reversed(a.root.children))
    assert to_json_bytes(a) == to_json_bytes(
        emit_ir(State(root=Column(id="screen", children=[first, second])), "1.0.0")
    )


def test_recursive_composition_has_definition_and_instance_context() -> None:
    from pycompose.errors import IrValidationError
    from pycompose.ui.composition import expand

    @composable
    def recursive():
        return recursive(id="again")

    with pytest.raises(IrValidationError, match="recursive composable") as exc:
        expand(recursive(id="start"))
    assert "recursive" in exc.value.context["source"]
    assert "start" in str(exc.value.context["composition"])


def test_composable_detaches_mutable_prop_containers() -> None:
    from pycompose.ui.composition import expand

    @composable
    def names(*, values):
        return Text(id="text", text=", ".join(values))

    values = ["Ada"]
    call = names(id="names", values=values)
    values.append("Grace")
    assert expand(call).props["text"] == "Ada"


def test_invalid_output_does_not_replace_the_last_good_bridge_snapshot() -> None:
    from dataclasses import replace

    from handlers import Handlers

    from pycompose.bridge import BridgeSurface
    from pycompose.state import Store

    @composable
    def broken():
        return None

    initial = State(root=Text(id="message", text="Hello"))
    store = Store(initial)
    actions = Handlers()
    actions.register(
        "increment", lambda state, _: replace(state, root=broken(id="broken"))
    )
    bridge = BridgeSurface(store, actions)
    snapshot = bridge.expose_latest_snapshot()
    bridge.accept_action('{"intent":"increment","payload":{"by":1}}')
    assert bridge.expose_latest_snapshot() == snapshot
    assert store.value is initial


def test_modifiers_are_forwarded_once_without_altering_internal_order() -> None:
    from pycompose.ui.composition import expand

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

    reuse = readable_reuse()
    snapshot = emit_ir(
        State(
            root=Scaffold(
                id="screen",
                top_bar=header(id="bar", text="Notes"),
                content=Column(id="body", children=(Text(id="line", text="hello"),)),
            )
        ),
        "1.0.0",
        reuse,
    )
    assert validate_ir(snapshot).snapshot is snapshot
    root = rename(to_dict(snapshot), reuse)["root"]
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

    reuse = Reuse()
    emit_ir(_rows(["Ada", "Grace"], row), "1.0.0", reuse)
    reused = emit_ir(_rows(["Ada", "Hopper"], row), "1.0.0", reuse)

    assert calls == ["Ada", "Grace", "Hopper"]
    fresh = emit_ir(_rows(["Ada", "Hopper"], row), "1.0.0")
    assert to_dict(reused) == to_dict(fresh)


def test_verification_catches_a_composable_reading_outside_its_inputs() -> None:
    outside = ["Ada"]

    @composable
    def row(*, name: str):
        return Text(id="name", text=f"{name} {outside[0]}")

    reuse = Reuse(ExpansionMemo(verify_every=1))
    emit_ir(_rows(["x"], row), "1.0.0", reuse)
    outside[0] = "Grace"
    with pytest.raises(IrValidationError, match="outside its arguments"):
        emit_ir(_rows(["x"], row), "1.0.0", reuse)
