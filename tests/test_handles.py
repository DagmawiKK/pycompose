"""Compact handles: a session names each node identity once, and never twice."""

from __future__ import annotations

from pycompose.components import Column, Text
from pycompose.core.ids import Handles
from pycompose.core.node import Node
from pycompose.core.reuse import Reuse
from pycompose.ir import emit_ir
from pycompose.state import State


def session() -> Reuse:
    """Return a release session's reuse, which names nodes compactly.

    Returns:
        A reuse with compact handles.
    """
    return Reuse(handles=Handles(compact=True))


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


def test_compact_names_are_short_and_stable_across_passes() -> None:
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


def test_readable_names_are_full_paths() -> None:
    emitted = emit_ir(column("a"), "1.0.0", Reuse()).root

    assert names(emitted) == {"a": "root.a"}
