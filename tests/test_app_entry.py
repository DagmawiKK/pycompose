"""The App entry: one object the session discovers, owning shell and view."""

from __future__ import annotations

import pytest

from pycompose.components import Text
from pycompose.errors import StateError
from pycompose.state import App, AppState, State
from pycompose.utils.json_canonical import canonical_json


class Shell(AppState):
    """A shell carrying the fields this entry contract exercises."""

    route: str = "home"
    taps: int = 0


def view(session: Shell) -> Text:
    """Render this shell.

    Args:
        session: The app's shell after the entry ran.

    Returns:
        The screen for this shell.
    """
    return Text(id="screen", text=f"{session.route}:{session.taps}")


def test_shell_app_seeds_renders_and_applies_the_host_route() -> None:
    app = App(state=Shell, view=view, route="route")

    state = app.build(route="notes", restore="")

    assert state.app == Shell(route="notes")
    assert state.version == 0
    assert state.root.props["text"] == "notes:0"


def test_shell_app_decodes_the_host_save_and_survives_a_corrupt_one() -> None:
    app = App(state=Shell, view=view, route="route")
    published = Shell(route="saved", taps=3)
    saved = canonical_json(State(root=view(published), app=published).data)

    restored = app.build(route="notes", restore=saved)
    assert restored.app == Shell(route="notes", taps=3)

    corrupt = app.build(route="notes", restore="{not json")
    assert corrupt.app == Shell(route="notes")


def test_an_app_without_a_route_field_keeps_its_saved_route() -> None:
    app = App(state=Shell, view=view)
    published = Shell(route="saved", taps=2)
    saved = canonical_json(State(root=view(published), app=published).data)

    restored = app.build(route="notes", restore=saved)

    assert restored.app == Shell(route="saved", taps=2)


def test_a_data_app_receives_the_saved_bytes_and_returns_the_first_state() -> None:
    def data_view(restore: str) -> State:
        return State(root=Text(id="screen", text=restore or "empty"))

    app = App(view=data_view)

    assert app.session_view is None
    assert app.build(route="any", restore="bytes").root.props["text"] == "bytes"
    assert app.build(route="any").root.props["text"] == "empty"


def test_a_misdeclared_entry_fails_at_import_time() -> None:
    with pytest.raises(StateError, match="shell seed"):
        App(state="no", view=view)  # type: ignore[arg-type]
    with pytest.raises(StateError, match="view"):
        App(state=Shell, view=None)  # type: ignore[arg-type]
    with pytest.raises(StateError, match="container"):
        App(state=Shell, view=view, container=3)  # type: ignore[arg-type]
    with pytest.raises(StateError, match="route"):
        App(state=Shell, view=view, route="")

    bad = App(state=lambda: State(root=Text(id="x", text="x")), view=view)  # type: ignore[arg-type]
    with pytest.raises(StateError, match="AppState"):
        bad.build(route="home")


def test_a_data_app_whose_view_returns_no_state_is_refused() -> None:
    app = App(view=lambda _restore: Text(id="screen", text="x"))  # type: ignore[arg-type, misc]

    with pytest.raises(StateError, match="return State"):
        app.build(route="home")
