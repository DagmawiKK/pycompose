"""Session-native actions: the handler's first parameter is the app shell."""

from __future__ import annotations

from types import ModuleType

import pytest

from pycompose import action
from pycompose.components import Text
from pycompose.core.effect import Effect
from pycompose.errors import StateError
from pycompose.state import AppState, Registry, State, actions_for_module, respond
from pycompose.state.app_action import AppAction


class Shell(AppState):
    """The shell these transitions move."""

    route: str = "home"
    about_open: bool = False


class Notes:
    """A stand-in for the app's use case."""


class Container:
    """A stand-in for the app's container."""


def view(session: Shell) -> Text:
    """Render this shell.

    Args:
        session: The shell after the transition.

    Returns:
        The screen for this shell.
    """
    open_mark = "open" if session.about_open else "closed"
    return Text(id="screen", text=f"{session.route}:{open_mark}")


def test_a_session_action_receives_its_shell_and_the_registry_rebuilds() -> None:
    actions = Registry()
    actions.install_view(view)

    @actions
    def open_about(session: Shell) -> Shell:
        return session.evolve(about_open=True)

    state = State(
        root=Text(id="screen", text="home:closed"),
        version=4,
        app=Shell(),
    )

    after = actions.dispatch("openAbout", state, None)

    assert after.app == Shell(about_open=True)
    assert after.version == 5
    assert after.root.props["text"] == "home:open"
    assert after.effects == ()


def test_a_classic_state_action_is_untouched_by_the_shell_path() -> None:
    actions = Registry()

    @actions
    def go(state: State) -> State:
        return State(root=Text(id="screen", text="went"), version=state.version + 1)

    state = State(root=Text(id="screen", text="home"), version=1, app=Shell())

    after = actions.dispatch("go", state, None)

    assert after.app is None
    assert after.version == 2
    assert after.root.props["text"] == "went"


def test_respond_carries_effects_and_a_returned_shell_requests_none() -> None:
    actions = Registry()
    actions.install_view(view)

    @actions
    def open_and_notify(session: Shell) -> Shell:
        return respond(session.evolve(about_open=True), Effect("toast", {"m": "hi"}))

    state = State(root=Text(id="screen", text="home:closed"), app=Shell())

    notified = actions.dispatch("openAndNotify", state, None)
    assert notified.effects == (Effect("toast", {"m": "hi"}),)
    assert notified.app == Shell(about_open=True)

    @actions
    def plain(session: Shell) -> Shell:
        return session

    settled = actions.dispatch("plain", state, None)
    assert settled.effects == ()
    assert settled.version == state.version + 1


def test_a_session_action_fails_closed_on_everything_it_cannot_honour() -> None:
    actions = Registry()

    @actions
    def open_about(session: Shell) -> Shell:
        return session.evolve(about_open=True)

    state = State(root=Text(id="screen", text="home"), app=Shell())
    stray = State(root=Text(id="screen", text="home"))

    with pytest.raises(StateError, match="view"):
        actions.dispatch("openAbout", state, None)

    actions.install_view(view)
    with pytest.raises(StateError, match="carrying its shell"):
        actions.dispatch("openAbout", stray, None)

    class Other(AppState):
        """A different app's shell."""

    wrong_shell = State(root=state.root, app=Other())
    with pytest.raises(StateError, match="carrying its shell"):
        actions.dispatch("openAbout", wrong_shell, None)

    @actions
    def wrong(session: Shell) -> object:  # noqa: ARG001
        return object()

    with pytest.raises(StateError, match="returns its shell"):
        actions.dispatch("wrong", state, None)

    @actions
    def wrong_respond(session: Shell) -> object:  # noqa: ARG001
        return respond(object())  # type: ignore[arg-type]

    with pytest.raises(StateError, match="respond"):
        actions.dispatch("wrongRespond", state, None)


def test_a_session_named_handler_without_a_shell_annotation_is_refused() -> None:
    with pytest.raises(StateError, match="shell type"):
        AppAction(lambda session, _payload: session)  # type: ignore[return-value, misc]


def test_injected_dependencies_and_payload_names_reach_a_session_action() -> None:
    notes = Notes()
    container = Container()
    container.notes = notes

    actions = Registry()
    actions.install_view(view)

    @actions
    def rename(session: Shell, note_id: int, value: str, *, notes: Notes) -> Shell:  # noqa: ARG001
        assert notes is container.notes
        return session.evolve(route=value)

    actions.install_container(container)
    state = State(root=Text(id="screen", text="home:closed"), app=Shell())
    after = actions.dispatch("rename", state, {"noteId": 7, "value": "away"})
    assert after.app == Shell(route="away")


def test_a_session_action_keeps_the_slices_it_did_not_touch() -> None:
    class Tab(AppState):
        index: int = 1

    actions = Registry()
    actions.install_view(view)
    slices = {"tab": Tab()}

    @actions
    def open_about(session: Shell) -> Shell:
        return session.evolve(about_open=True)

    state = State(
        root=Text(id="screen", text="home:closed"),
        app=Shell(),
        slices=slices,
    )

    after = actions.dispatch("openAbout", state, None)

    assert after.slices == slices
    assert after.app == Shell(about_open=True)


def test_the_boot_seam_installs_the_shell_view_on_a_discovered_registry() -> None:
    @action
    def open_about(session: Shell) -> Shell:
        return session.evolve(about_open=True)

    module = ModuleType("entry")
    module.open_about = open_about

    actions, problem = actions_for_module(module, view)

    assert problem is None
    moved = actions.dispatch("openAbout", State(root=view(Shell()), app=Shell()))
    assert moved.app == Shell(about_open=True)


def test_a_data_mode_entry_defining_a_session_action_fails_at_boot() -> None:
    @action
    def open_about(session: Shell) -> Shell:
        return session.evolve(about_open=True)

    module = ModuleType("entry")
    module.open_about = open_about

    actions, problem = actions_for_module(module, None)

    # Refused before the first frame, not on the first tap: a session-native
    # action with no view installed can only fail once a user triggers it.
    assert problem is not None
    assert "shell" in problem
    assert actions.handlers() == {}
