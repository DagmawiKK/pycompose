"""A composable taking the shell re-runs only when a field it read changes."""

from __future__ import annotations

from pycompose import composable
from pycompose.model.nodes.expansion import ExpansionMemo
from pycompose.model.nodes.node import Node
from pycompose.model.nodes.reuse import Reuse
from pycompose.model.snapshot import Snapshot
from pycompose.state import AppState
from pycompose.ui import Column, Text
from pycompose.wire import emit_ir

runs: list[str] = []


class Shell(AppState):
    count: int = 0
    status: str = "idle"


@composable
def counter(*, session: Shell) -> Node:
    runs.append("counter")
    return Text(text=str(session.count))


@composable
def screen(*, session: Shell) -> Node:
    runs.append("screen")
    return Column(children=[counter(session=session), Text(text=session.status)])


def publish(reuse: Reuse, shell: Shell, root: Node | None = None) -> None:
    emit_ir(Snapshot(root=root or counter(session=shell)), "1.0.0", reuse)


def test_a_change_to_a_field_it_did_not_read_reuses_its_output() -> None:
    reuse = Reuse(ExpansionMemo())
    runs.clear()
    publish(reuse, Shell())
    publish(reuse, Shell(status="busy"))

    assert runs == ["counter"]


def test_a_change_to_a_field_it_read_re_runs_it_and_says_why() -> None:
    memo = ExpansionMemo()
    reuse = Reuse(memo)
    runs.clear()
    publish(reuse, Shell())
    publish(reuse, Shell(count=1))

    assert runs == ["counter", "counter"]
    assert memo.reasons == [f"{counter.source}: session.count changed"]


def test_a_parent_passing_the_shell_on_re_runs_so_its_child_sees_the_new_one() -> None:
    reuse = Reuse(ExpansionMemo())
    first, second = Shell(), Shell(count=1)
    runs.clear()
    publish(reuse, first, screen(session=first))
    publish(reuse, second, screen(session=second))

    assert runs == ["screen", "counter", "screen", "counter"]
