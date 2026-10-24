"""Python entrypoint for the generated app.

The components come from the app's own generated package, which the build
regenerates from what this source references (ADR-0014), so the app ships the
components it uses and nothing else.
"""

from m3 import Text
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
