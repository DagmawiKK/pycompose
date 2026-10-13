"""Counter entrypoint exercising worker-owned composition and native actions."""

from pycompose import composable
from pycompose.bridge.generated_payloads import IncrementPayload
from pycompose.core import Node
from pycompose.m3 import Column, FilledButton, Image, Modifier, Text
from pycompose.state import Actions, State

actions = Actions()


@composable
def counter(*, count: int) -> Node:
    return Column(
        id="content",
        modifier=Modifier().padding(24),
        children=[
            Text(id="count", text=f"Count: {count}", style="headlineMedium"),
            FilledButton(id="add", text="Add", on_click="increment"),
            Text(
                id="localized",
                text="Greeting unavailable",
                resource="@string/pycompose_greeting",
                locale="fr",
            ),
            Image(
                id="logo",
                resource="@drawable/ic_pycompose",
                content_description="PyCompose logo",
                modifier=Modifier().size(96),
            ),
            Text(
                id="asset", text="Asset unavailable", resource="@asset/demo/message.txt"
            ),
        ],
    )


def build() -> State:
    return State(root=counter(id="counter", count=0))


def increment(state: State, payload: IncrementPayload) -> State:
    count = state.version + payload.get("by", 1)
    return State(root=counter(id="counter", count=count), version=count)


actions.register("increment", increment)
