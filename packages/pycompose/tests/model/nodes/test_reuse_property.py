"""Over any sequence of edits, a session's reuse publishes exactly a fresh build."""

from __future__ import annotations

import json

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from readable import readable_reuse, rename

from pycompose import composable
from pycompose.foundation import Column
from pycompose.material3 import Text
from pycompose.model.nodes.node import Node
from pycompose.model.nodes.reuse import Reuse
from pycompose.model.snapshot import Snapshot
from pycompose.wire import emit_ir, to_json, validate_ir


@composable
def row(*, label: str, extra: bool) -> Node:
    children = [Text(text=label)]
    if extra:
        children.append(Text(text=f"{label}!"))
    return Column(children=children)


def publish(state: Snapshot, reuse: Reuse | None) -> dict[str, object]:
    """Publish ``state`` in a session, or fresh, naming nodes by readable path.

    Names are a session's own, so a session and a fresh build agree on what
    each node is, not on its counter: compare them by the path debug keeps.
    """
    reuse = reuse or readable_reuse()
    result = validate_ir(emit_ir(state, "1.0.0", reuse), reuse=reuse)
    assert result.snapshot is not None
    return rename(json.loads(to_json(result.snapshot, reuse)), reuse)


class Session(RuleBasedStateMachine):
    """A screen of keyed rows edited at random, published after every edit."""

    def __init__(self) -> None:
        super().__init__()
        self.labels: list[str] = ["a", "b"]
        self.extra: set[str] = set()
        self.title = "Rows"
        self.session = readable_reuse()

    def state(self) -> Snapshot:
        rows = [
            row(id=f"r_{label}", label=label, extra=label in self.extra)
            for label in self.labels
        ]
        return Snapshot(root=Column(children=[Text(text=self.title), *rows]))

    @rule(label=st.sampled_from("abcdefg"))
    def add(self, label: str) -> None:
        if label not in self.labels:
            self.labels.append(label)

    @rule(index=st.integers(0, 6))
    def remove(self, index: int) -> None:
        if self.labels:
            self.labels.pop(index % len(self.labels))

    @rule()
    def reverse(self) -> None:
        self.labels.reverse()

    @rule(label=st.sampled_from("abcdefg"))
    def toggle(self, label: str) -> None:
        self.extra ^= {label}

    @rule(title=st.text(min_size=1, max_size=5))
    def rename(self, title: str) -> None:
        self.title = title

    @invariant()
    def reuse_matches_a_fresh_build(self) -> None:
        state = self.state()
        assert publish(state, self.session) == publish(state, None)


TestSession = Session.TestCase
TestSession.settings = settings(max_examples=60, stateful_step_count=20, deadline=None)
