"""Publishing with a session's reuse is byte-for-byte a fresh publish."""

import json

import pytest
from readable import readable_reuse, rename

from pycompose import composable
from pycompose.core.node import Node, Props
from pycompose.core.reuse import Reuse
from pycompose.errors import IrError
from pycompose.ir import emit_ir, to_json, validate_ir
from pycompose.m3 import Column, Text
from pycompose.state import State


@composable
def row(*, label: str, extra: bool):
    children = [Text(id="label", text=label)]
    if extra:
        children.append(Text(id="extra", text=f"{label}!"))
    return Column(id="row", children=tuple(children))


def _state(labels: list[str], *, extra: bool = False, title: str = "Rows") -> State:
    rows = tuple(row(id=f"r_{label}", label=label, extra=extra) for label in labels)
    return State(
        root=Column(id="screen", children=(Text(id="title", text=title), *rows))
    )


def _publish(state: State, reuse: Reuse | None) -> str:
    """Publish in a session, or fresh, with ids replaced by readable paths."""
    reuse = reuse or readable_reuse()
    result = validate_ir(emit_ir(state, "1.0.0", reuse), reuse=reuse)
    return json.dumps(rename(json.loads(to_json(result.snapshot, reuse)), reuse))


SEQUENCE = [
    _state(["a", "b", "c"]),
    _state(["a", "b", "c"], title="Renamed"),
    _state(["c", "a", "b"], title="Renamed"),
    _state(["c", "a", "d", "b"], title="Renamed"),
    _state(["a", "b"], extra=True),
    _state(["a", "b"], extra=True),
    _state(["b"]),
]


def test_a_reused_publish_matches_a_fresh_one_at_every_step() -> None:
    reuse = readable_reuse()
    for state in SEQUENCE:
        assert _publish(state, reuse) == _publish(state, None)


def test_a_duplicate_id_across_reused_subtrees_is_still_refused() -> None:
    reuse = readable_reuse()
    _publish(_state(["a", "b"]), reuse)
    # Components refuse duplicate sibling keys on construction; a raw node does
    # not, so the emitter's claim is what must refuse it, reused or not.
    duplicate = State(
        root=Node(
            id="screen",
            type="Column",
            props=Props({}),
            children=(
                row(id="r_a", label="a", extra=False),
                row(id="r_a", label="a", extra=False),
            ),
        )
    )
    with pytest.raises(IrError):
        _publish(duplicate, None)
    with pytest.raises(IrError):
        _publish(duplicate, reuse)
