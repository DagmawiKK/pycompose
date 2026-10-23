"""Over any sequence of edits, a session's reuse publishes exactly a fresh build."""

from __future__ import annotations

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from pycompose import composable
from pycompose.core.ids import Handles
from pycompose.core.node import Node
from pycompose.core.reuse import Reuse
from pycompose.ir import emit_ir, to_json, validate_ir
from pycompose.m3 import Column, Text
from pycompose.state import State


@composable
def row(*, label: str, extra: bool) -> Node:
    children = [Text(text=label)]
    if extra:
        children.append(Text(text=f"{label}!"))
    return Column(children=children)


def publish(state: State, reuse: Reuse | None) -> str:
    result = validate_ir(emit_ir(state, "1.0.0", reuse), reuse=reuse)
    assert result.snapshot is not None
    return to_json(result.snapshot, reuse)


class Session(RuleBasedStateMachine):
    """A screen of keyed rows edited at random, published after every edit."""

    def __init__(self) -> None:
        super().__init__()
        self.labels: list[str] = ["a", "b"]
        self.extra: set[str] = set()
        self.title = "Rows"
        self.readable = Reuse()
        self.compact = Reuse(handles=Handles(compact=True))

    def state(self) -> State:
        rows = [
            row(id=f"r_{label}", label=label, extra=label in self.extra)
            for label in self.labels
        ]
        return State(root=Column(children=[Text(text=self.title), *rows]))

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
        assert publish(state, self.readable) == publish(state, None)
        publish(state, self.compact)


TestSession = Session.TestCase
TestSession.settings = settings(max_examples=60, stateful_step_count=20, deadline=None)
