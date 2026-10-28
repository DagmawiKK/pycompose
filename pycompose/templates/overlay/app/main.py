"""Python entrypoint for the generated app.

The components come from the app's own generated package, which the build
regenerates from what this source references (ADR-0014), so the app ships the
components it uses and nothing else.
"""

from m3 import Text
from pycompose.app import App, Destination, ViewModel
from pycompose.state import AppState


class Greeting(AppState):
    """What the screen shows; saved across process death."""


class GreetingViewModel(ViewModel[Greeting]):
    """The screen's state and behaviour."""

    def __init__(self) -> None:
        super().__init__(Greeting())


def screen(state: Greeting) -> Text:
    """Draw the screen from its state.

    Args:
        state: The view model's state.

    Returns:
        The greeting.
    """
    return Text(id="greeting", text="Hello PyCompose")


app = App(start=Destination(lambda _container, _route: GreetingViewModel(), screen))
