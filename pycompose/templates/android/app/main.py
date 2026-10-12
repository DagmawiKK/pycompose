"""Python entrypoint for the generated app."""

from pycompose.components import Text
from pycompose.state import State


def build() -> State:
    """Build the initial app state and its declarative screen."""
    return State(root=Text(id="greeting", text="Hello PyCompose"))
