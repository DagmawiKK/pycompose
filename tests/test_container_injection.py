"""Container injection: what an action may ask for, and when it finds out.

The interesting cases are the failures. A DI framework reports a missing
binding at compile time; this reports it when the session starts. Both are
before the first frame, which is the only part of that guarantee worth having.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TypedDict

import pytest

from pycompose import AppContext, action, install_context
from pycompose.bridge.runtime import RuntimeSession
from pycompose.errors import BridgeError, StateError
from pycompose.state import Actions, State

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"


class Nothing(TypedDict):
    pass


class NoteId(TypedDict):
    note_id: int


class Container:
    """A stand-in for an app's container."""

    def __init__(self, tag: str = "real") -> None:
        self.tag = tag


@pytest.fixture(scope="module")
def notes(request: pytest.FixtureRequest) -> Any:
    """Import the Notes app the way the on-device worker does.

    Leaving ``main`` in ``sys.modules`` would break the dev-server tests, whose
    entrypoint loader refuses a name something else already imported -- so the
    import is undone on the way out, not just the path entry.

    Args:
        request: The fixture request, used to schedule the teardown.

    Returns:
        The app entrypoint module.
    """
    sys.path.insert(0, str(APP))
    request.addfinalizer(lambda: sys.modules.pop("main", None))
    request.addfinalizer(lambda: sys.path.remove(str(APP)))
    import main

    return main


def _state() -> State:
    """Return an empty starting snapshot.

    Returns:
        A State with no screen, for a handler that returns its input.
    """
    from pycompose.core import Node

    return State(root=Node(id="root", type="Text", props={}))


# ---------------------------------------------------------------------------
# What an action is allowed to ask for
# ---------------------------------------------------------------------------


def test_an_action_may_take_a_keyword_only_container() -> None:
    def handler(state: State, payload: Nothing, *, container: Container) -> State:
        return state

    assert action(handler).injected == ("container",)


def test_an_action_may_take_nothing_extra() -> None:
    def handler(state: State, payload: Nothing) -> State:
        return state

    assert action(handler).injected == ()


def test_a_third_positional_parameter_is_refused() -> None:
    """Positional injection would let a misplaced argument pass unnoticed."""

    def handler(state: State, payload: Nothing, container: Container) -> State:
        return state

    with pytest.raises(StateError, match="keyword-only"):
        action(handler)


def test_an_action_may_ask_for_anything_the_container_carries() -> None:
    """Asking for a use case beats asking for the object that holds it."""

    def handler(state: State, payload: Nothing, *, notes: Container) -> State:
        return state

    assert action(handler).injected == ("notes",)


def test_a_dependency_the_container_lacks_is_refused_at_startup() -> None:
    """Not silently None -- the session names what it could not find."""

    def handler(state: State, payload: Nothing, *, absent: Container) -> State:
        return state

    definition = action(handler)
    registry = Actions(definition)
    registry.install_container(Container())
    with pytest.raises(StateError, match="carries no such dependency"):
        registry.dispatch(definition.name, _state(), {})


def test_the_injection_set_is_decided_once_not_per_dispatch() -> None:
    """Dispatch reflects on nothing, so the signature is read exactly once."""

    def handler(state: State, payload: Nothing, *, container: Container) -> State:
        return state

    definition = action(handler)
    assert definition.injected == ("container",)
    assert definition.function.__name__ == "handler"


# ---------------------------------------------------------------------------
# Calling an action directly -- the zero-setup test
# ---------------------------------------------------------------------------


def test_an_action_is_callable_so_a_test_needs_no_runtime() -> None:
    """This is what makes a unit test two lines instead of a harness."""

    @action
    def noop(state: State, payload: Nothing, *, container: Container) -> State:
        return state

    supplied = Container("fake")
    assert noop(_state(), {}, container=supplied) is not None


def test_the_app_s_actions_run_without_a_bridge(notes: Any) -> None:
    """The claim from the design: no mocks, no reflection, no session."""
    from notes_app.container import AppContainer
    from notes_app.data.notes_repo import MemoryNotesRepo
    from notes_app.domain import Notes
    from notes_app.domain.models import Note

    # A session installs both of these. This test stands in for one, and must
    # do it before build: a composable reached during the first render resolves
    # its registry from the context.
    supplied = AppContainer(Notes(MemoryNotesRepo([Note(1, "Only")])))
    notes.actions.install_container(supplied)
    install_context(
        AppContext(actions=notes.actions, container=supplied, notes=supplied.notes)
    )
    start = notes.build(route="notes", restore="", container=supplied)

    # Call the decorated action itself, the way a developer would in a test.
    delete = notes.actions._contracts["notes_app.actions.delete_note"]
    delete.function(start, {"note_id": 1}, notes=supplied.notes)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_registry_reports_what_its_actions_want() -> None:
    @action
    def wants(state: State, payload: Nothing, *, container: Container) -> State:
        return state

    @action
    def does_not(state: State, payload: Nothing) -> State:
        return state

    assert Actions(wants, does_not).injected == ("container",)


def test_a_registry_of_plain_handlers_wants_nothing() -> None:
    assert Actions().injected == ()


def test_an_action_without_a_container_is_refused_at_dispatch() -> None:
    """Reached only outside a session; the session catches this at startup."""

    @action
    def wants(state: State, payload: Nothing, *, container: Container) -> State:
        return state

    registry = Actions(wants)
    with pytest.raises(StateError, match="declared none"):
        registry.dispatch(wants.name, _state(), {})


def test_an_installed_container_is_supplied_on_dispatch() -> None:
    seen: list[Any] = []

    @action
    def wants(state: State, payload: Nothing, *, container: Container) -> State:
        seen.append(container)
        return state

    registry = Actions(wants)
    supplied = Container()
    registry.install_container(supplied)
    registry.dispatch(wants.name, _state(), {})
    assert seen == [supplied]


# ---------------------------------------------------------------------------
# Failing at startup, not at the first tap
# ---------------------------------------------------------------------------


def test_a_session_refuses_an_app_whose_actions_want_a_container_it_declares_none(
    tmp_path: Path,
) -> None:
    """The whole point: a missing binding is a boot failure, named clearly."""
    app_dir = tmp_path / "unwired"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("")
    (app_dir / "main.py").write_text(
        "from typing import TypedDict\n"
        "from pycompose import AppContext, action, install_context\n"
        "from pycompose.state import Actions, State\n"
        "\n"
        "class Nothing(TypedDict):\n"
        "    pass\n"
        "\n"
        "@action\n"
        "def wants(state: State, payload: Nothing, *, container: object) -> State:\n"
        "    return state\n"
        "\n"
        "actions = Actions(wants)\n"
        "\n"
        "def build(*, route: str = '', restore: str = '') -> State:\n"
        "    return state_placeholder()\n"
        "\n"
        "def state_placeholder() -> State:\n"
        "    from pycompose.core import Node\n"
        "    return State(root=Node(id='root', type='Text', props={}))\n"
    )
    sys.path.insert(0, str(tmp_path))
    try:
        # At construction, before a single frame: the whole point of the check.
        with pytest.raises(BridgeError, match="declares none"):
            RuntimeSession("unwired.main:build", "notes", debug=True)
    finally:
        sys.path.remove(str(tmp_path))
        for name in [n for n in sys.modules if n.startswith("unwired")]:
            del sys.modules[name]


def test_the_notes_app_starts_with_its_container_installed(notes: Any) -> None:
    """The real app, through the real session, declares and receives one."""
    import tempfile

    from pycompose.repository import use_root

    scratch = Path(tempfile.mkdtemp())
    use_root(scratch)
    try:
        session = RuntimeSession("main:build", "notes", debug=True)
        assert session.error() == ""
        container = notes.container()
        # What the session installed, reached the way an action reaches it.
        assert container.notes.list() == []
        assert notes.actions.injected == ("notes",)
    finally:
        use_root(Path.cwd())
