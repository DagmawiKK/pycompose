"""Python entrypoint for the generated app."""

from pycompose.components import Text
from pycompose.state import App, AppState


class Session(AppState):
    """The shell this app remembers across process death."""


def view(session: Session) -> Text:
    """Compose the screen for this shell.

    Args:
        session: The app's shell, restored from the bytes the host saved.

    Returns:
        The greeting screen.
    """
    return Text(id="greeting", text="Hello PyCompose")


app = App(state=Session, view=view)
