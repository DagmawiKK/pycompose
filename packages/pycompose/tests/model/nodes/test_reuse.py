"""Publishing with a session's reuse is byte-for-byte a fresh publish."""

import json

import pytest
from readable import readable_reuse, rename

from pycompose import composable
from pycompose.errors import IrError
from pycompose.host.wire import emit_ir, to_json, validate_ir
from pycompose.model.nodes.node import Node, Props
from pycompose.model.nodes.reuse import Reuse
from pycompose.model.nodes.windows import windows
from pycompose.model.snapshot import Snapshot
from pycompose.ui import Column, LazyColumn, Text


@composable
def row(*, label: str, extra: bool):
    children = [Text(id="label", text=label)]
    if extra:
        children.append(Text(id="extra", text=f"{label}!"))
    return Column(id="row", children=tuple(children))


def _state(labels: list[str], *, extra: bool = False, title: str = "Rows") -> Snapshot:
    rows = tuple(row(id=f"r_{label}", label=label, extra=extra) for label in labels)
    return Snapshot(
        root=Column(id="screen", children=(Text(id="title", text=title), *rows))
    )


def _publish(state: Snapshot, reuse: Reuse | None) -> str:
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


@composable
def listing(*, title: str):
    return Column(
        id="listing",
        children=(
            Text(id="title", text=title),
            LazyColumn(
                id="rows",
                items=range(1_000),
                key=lambda n: f"n{n}",
                item=lambda n: row(id=f"r{n}", label=str(n), extra=False),
            ),
        ),
    )


def test_a_reused_publish_follows_a_window_inside_a_composable() -> None:
    state = Snapshot(root=listing(id="screen", title="Rows"))
    reuse = readable_reuse()
    first_pass = json.loads(_publish(state, reuse))
    key = first_pass["root"]["children"][1]["props"]["window"]
    for first in (0, 400, 400, 900, 0):
        with windows({key: (first, first + 9)}):
            reused = _publish(state, reuse)
            assert reused == _publish(state, None)
            assert f'"itemOffset": {first}' in reused


def test_a_duplicate_id_across_reused_subtrees_is_still_refused() -> None:
    reuse = readable_reuse()
    _publish(_state(["a", "b"]), reuse)
    # Components refuse duplicate sibling keys on construction; a raw node does
    # not, so the emitter's claim is what must refuse it, reused or not.
    duplicate = Snapshot(
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
