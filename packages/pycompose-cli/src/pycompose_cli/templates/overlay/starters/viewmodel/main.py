"""Your app: a view model, an intent, and a screen drawn from its state.

This is the full-control starting point: you own each screen's state and
behaviour and draw it with native components. Add routes and more screens as
the README shows; the notes example is a complete app built this way.
"""

from components import Button, Column, Modifier, Text
from pycompose.app import App, Destination, Intent, ViewModel
from pycompose.state import AppState


class Counter(AppState):
    """What the screen shows; saved across process death."""

    count: int = 0


class Increment(Intent):
    """Add one to the count."""


class CounterViewModel(ViewModel[Counter]):
    """The screen's state and behaviour."""

    def __init__(self) -> None:
        super().__init__(Counter())

    def on_intent(self, intent: Intent) -> None:
        """Handle a tap.

        Args:
            intent: What the control asked for.
        """
        if isinstance(intent, Increment):
            self.state = self.state.evolve(count=self.state.count + 1)


def screen(state: Counter) -> Column:
    """Draw the count and the button that moves it.

    Args:
        state: The view model's state.

    Returns:
        The screen.
    """
    return Column(
        modifier=Modifier().padding(24),
        children=[
            Text(text=f"Tapped {state.count} times"),
            Button(text="Tap me", on_click=Increment()),
        ],
    )


app = App(start=Destination(lambda _container, _route: CounterViewModel(), screen))
