"""Handles: a session names each node identity once, and never twice."""

from __future__ import annotations

from pycompose.components import Column, Text
from pycompose.core.ids import Handles
from pycompose.core.node import Node
from pycompose.core.reuse import Reuse
from pycompose.ir import emit_ir
from pycompose.ir.patch import PatchOp, ReplaceSubtree, diff_nodes
from pycompose.state import State


def session(*, readable: bool = False) -> Reuse:
    """Return a session's reuse; a debug one also keeps readable paths.

    Args:
        readable: Keep each name's readable path, as debug does.

    Returns:
        A reuse with its own handles.
    """
    return Reuse(handles=Handles(readable=readable))


def names(root: Node) -> dict[str, str]:
    """Map each child's text to its emitted id.

    Args:
        root: An emitted column of texts.

    Returns:
        Text to id.
    """
    return {str(child.props["text"]): child.id for child in root.children}


def column(*labels: str) -> State:
    """Return a column with one keyed text per label.

    Args:
        *labels: Texts, each also its key.

    Returns:
        The state.
    """
    return State(
        root=Column(
            id="list", children=[Text(id=label, text=label) for label in labels]
        )
    )


def test_names_are_short_and_stable_across_passes() -> None:
    reuse = session()

    first = emit_ir(column("a", "b"), "1.0.0", reuse).root
    second = emit_ir(column("a", "b"), "1.0.0", reuse).root

    assert names(first) == names(second)
    assert all(len(name) <= 2 for name in names(first).values())


def test_a_keyed_reorder_keeps_each_childs_name() -> None:
    reuse = session()

    before = names(emit_ir(column("a", "b", "c"), "1.0.0", reuse).root)
    after = names(emit_ir(column("c", "a", "b"), "1.0.0", reuse).root)

    assert before == after


def test_a_name_is_never_given_to_a_second_identity() -> None:
    reuse = session()

    gone = names(emit_ir(column("a", "b"), "1.0.0", reuse).root)["b"]
    fresh = names(emit_ir(column("a", "c"), "1.0.0", reuse).root)["c"]

    assert fresh != gone


def test_forgetting_old_identities_keeps_the_live_ones() -> None:
    reuse = session()
    emit_ir(column(*(f"old{n}" for n in range(50))), "1.0.0", reuse)

    kept = names(emit_ir(column("a", "b"), "1.0.0", reuse).root)
    again = names(emit_ir(column("a", "b", "c"), "1.0.0", reuse).root)

    assert again["a"] == kept["a"]
    assert again["b"] == kept["b"]


def test_debug_keeps_each_names_full_path_off_the_wire() -> None:
    reuse = session(readable=True)
    emitted = emit_ir(column("a"), "1.0.0", reuse).root
    paths = reuse.handles.paths()

    assert {text: paths[name] for text, name in names(emitted).items()} == {
        "a": "root.a"
    }
    assert paths[emitted.id] == "root"
    assert session().handles.paths() == {}


def _rows(labels: list[str], *, title: str = "Rows") -> State:
    return State(
        root=Column(
            id="screen",
            children=[
                Text(id="title", text=title),
                *(
                    Column(id=f"r_{label}", children=[Text(text=label)])
                    for label in labels
                ),
            ],
        )
    )


SEQUENCE = [
    _rows(["a", "b", "c"]),
    _rows(["a", "b", "c"], title="Renamed"),
    _rows(["c", "a", "b"], title="Renamed"),
    _rows(["c", "a", "d", "b"]),
    _rows(["b"]),
    *(_rows([f"n{n}"]) for n in range(8)),
    _rows(["a", "b"]),
]


def _pairs(node: Node, paths: dict[str, str]) -> list[tuple[str, str]]:
    pairs = [(paths[node.id], node.id)]
    for child in node.children:
        pairs += _pairs(child, paths)
    return pairs


def test_each_identity_keeps_one_name_and_no_name_is_reused() -> None:
    reuse = session(readable=True)
    owners: dict[str, str] = {}
    previous: dict[str, str] = {}
    for state in SEQUENCE:
        root = emit_ir(state, "1.0.0", reuse).root
        current = dict(_pairs(root, reuse.handles.paths()))
        for path, name in current.items():
            # A name is never given to a second identity, and an identity that
            # lives on from one snapshot to the next keeps its name.
            assert owners.setdefault(name, path) == path
            assert previous.get(path, name) == name
        previous = current


def test_patches_rebuild_each_snapshot_from_the_last() -> None:
    reuse = session()
    previous = emit_ir(SEQUENCE[0], "1.0.0", reuse).root
    for state in SEQUENCE[1:]:
        latest = emit_ir(state, "1.0.0", reuse).root
        rebuilt = previous
        for op in diff_nodes(previous, latest):
            rebuilt = _apply(rebuilt, op, op.at)
        assert rebuilt == latest
        previous = latest


def _apply(node: Node, op: PatchOp, at: tuple[int, ...]) -> Node:
    if not at:
        assert node.id == op.id
        if isinstance(op, ReplaceSubtree):
            return op.payload
        props = {**node.props.values, op.prop: op.value}
        return Node(id=node.id, type=node.type, props=props, children=node.children)
    children = list(node.children)
    children[at[0]] = _apply(children[at[0]], op, at[1:])
    return Node(
        id=node.id, type=node.type, props=node.props, children=children, slot=node.slot
    )
