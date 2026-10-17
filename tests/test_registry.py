"""The action registry: one declaration per action, and loud failures.

Two properties matter here and they pull in opposite directions. An app should
never have to list its actions twice, and an app that gets the wiring wrong
should never boot to a blank screen. Every test below is one or the other.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TypedDict

import pytest

from pycompose import Registry
from pycompose.bridge.runtime import RuntimeSession
from pycompose.errors import BridgeError, StateError
from pycompose.state import State

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"


class Nothing(TypedDict):
    pass


def _state(text: str = "start") -> State:
    """Return a minimal snapshot.

    Args:
        text: The text the root node shows.

    Returns:
        A State carrying one Text node.
    """
    from pycompose.m3 import Text

    return State(root=Text(id="text", text=text))


# ---------------------------------------------------------------------------
# Registration is the definition
# ---------------------------------------------------------------------------


def test_a_registry_collects_the_actions_it_defines() -> None:
    actions = Registry()

    @actions
    def first(state: State, payload: Nothing) -> State:
        return state

    assert actions.names() == ("first",)
    assert actions.first is first


def test_a_registry_is_an_actions_registry() -> None:
    """The session finds one and the bridge accepts one, unchanged."""
    from pycompose.state import Actions

    assert isinstance(Registry(), Actions)


def test_a_seeded_registry_starts_populated() -> None:
    actions = Registry()

    @actions
    def only(state: State, payload: Nothing) -> State:
        return state

    again = Registry(only)
    assert again.names() == ("only",)


def test_an_action_is_reachable_by_its_bare_and_qualified_name() -> None:
    actions = Registry()

    @actions
    def new_note(state: State, payload: Nothing) -> State:
        return state

    assert new_note.name in actions
    assert "newNote" in actions
    assert actions.new_note.bind(id="n1").startswith("app.")


def test_defining_the_same_action_twice_is_refused() -> None:
    actions = Registry()

    @actions
    def twin(state: State, payload: Nothing) -> State:
        return state

    with pytest.raises(StateError, match="duplicate"):

        @actions
        def twin(state: State, payload: Nothing) -> State:
            return state


def test_asking_for_an_action_that_was_never_defined_says_what_is() -> None:
    """A typo should not be an AttributeError with no clue."""
    actions = Registry()

    @actions
    def delete_note(state: State, payload: Nothing) -> State:
        return state

    with pytest.raises(AttributeError, match="holds delete_note"):
        _ = actions.delete_notes


def test_an_empty_registry_names_nothing_rather_than_raising() -> None:
    assert Registry().names() == ()


# ---------------------------------------------------------------------------
# The blank-screen failure, refused
# ---------------------------------------------------------------------------


APP_SOURCE = """from typing import TypedDict
from pycompose import Registry
from pycompose.m3 import Text
from pycompose.state import App, AppState, State

class Nothing(TypedDict):
    pass

class Shell(AppState):
    route: str = "home"

actions = Registry()

@actions
def ping(state: State, payload: Nothing) -> State:
    return State(root=Text(id="text", text="pong"))

def view(shell: Shell) -> Text:
    return Text(id="text", text=shell.route)

app = App(state=Shell, view=view, route="route")
"""


def _write(tmp_path: Path, source: str, name: str = "reg_app") -> Path:
    """Write a generated app package and make it importable.

    Args:
        tmp_path: Where to create it.
        source: The entrypoint's source.
        name: The package name.

    Returns:
        The package directory.
    """
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "main.py").write_text(source)
    sys.path.insert(0, str(tmp_path))
    return package


@pytest.fixture
def generated(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    """Provide a factory that writes a generated app package.

    Args:
        request: The fixture request, used to schedule the teardown.
        tmp_path: Where each generated package is created.

    Returns:
        A callable taking source and package name, returning the package.
    """

    def write(source: str, name: str = "reg_app") -> Path:
        package = _write(tmp_path, source, name)
        return package

    def clean() -> None:
        sys.path.remove(str(tmp_path))
        for module in [n for n in sys.modules if n.startswith("reg_app")]:
            del sys.modules[module]
        for module in [n for n in sys.modules if n.startswith(("misnamed", "silent"))]:
            del sys.modules[module]

    request.addfinalizer(clean)
    return write


def test_a_registry_that_actually_works_starts(generated: Any) -> None:
    generated(APP_SOURCE)
    session = RuntimeSession("reg_app.main:app", "home", debug=True)
    assert session.error() == ""
    assert json.loads(session.snapshot())["root"]["props"]["text"] == "home"


def test_a_registry_built_somewhere_else_is_refused(generated: Any) -> None:
    """The historical failure: real actions exist, the entrypoint exposes none.

    Declaring them under a name the session does not look for leaves an app
    that starts, renders, and does nothing -- every control inert because no
    binding resolves. That is exactly what this refuses.
    """
    generated(
        "from typing import TypedDict\n"
        "from pycompose import Registry\n"
        "from pycompose.m3 import Text\n"
        "from pycompose.state import Actions, App, State\n"
        "\n"
        "class Nothing(TypedDict):\n"
        "    pass\n"
        "\n"
        "built_elsewhere = Registry()\n"
        "\n"
        "@built_elsewhere\n"
        "def ping(state: State, payload: Nothing) -> State:\n"
        "    return State(root=Text(id='text', text='pong'))\n"
        "\n"
        "# The misspelling: the actions are here, the registry is not.\n"
        "actions = Actions()\n"
        "\n"
        "def view(restore: str) -> State:\n"
        "    return State(root=Text(id='text', text='home'))\n"
        "\n"
        "app = App(view=view)\n",
        name="misnamed",
    )
    with pytest.raises(BridgeError, match="holds nothing"):
        RuntimeSession("misnamed.main:app", "home", debug=True)


def test_an_app_with_no_actions_at_all_still_starts(generated: Any) -> None:
    """Declaring nothing is legitimate; declaring something empty is not."""
    generated(
        "from pycompose.m3 import Text\n"
        "from pycompose.state import App, AppState\n"
        "class Shell(AppState):\n"
        "    route: str = ''\n"
        "def view(shell: Shell) -> Text:\n"
        "    return Text(id='text', text=shell.route)\n"
        "app = App(state=Shell, view=view, route='route')\n",
        name="silent",
    )
    session = RuntimeSession("silent.main:app", "home", debug=True)
    assert json.loads(session.snapshot())["root"]["props"]["text"] == "home"


# ---------------------------------------------------------------------------
# The real app, after the change
# ---------------------------------------------------------------------------


def test_the_notes_app_declares_each_action_exactly_once() -> None:
    """No listing anywhere: the decorator is the registration."""
    sys.path.insert(0, str(APP))
    try:
        import notes_app.actions  # noqa: F401 - registers the package

        # The package re-exports the registry under the name `actions`, which
        # shadows the submodule of the same name; sys.modules is the way in.
        module = sys.modules["notes_app.actions"]
    finally:
        sys.path.remove(str(APP))

    source = (APP / "notes_app" / "actions.py").read_text()
    declared = len(
        [
            line
            for line in source.splitlines()
            if line.startswith(("@action", "@actions"))
        ]
    )
    assert declared == len(module.actions.names())
    assert len(module.actions.names()) == 14


def test_the_notes_app_has_no_handler_dataclass_left() -> None:
    """The cycle-breaker module existed only to be a second list of actions."""
    assert not (APP / "notes_app" / "handlers.py").exists()
    assert "Handlers" not in (APP / "notes_app" / "view_model.py").read_text()


# ---------------------------------------------------------------------------
# Names a registry already uses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["add", "names", "dispatch", "register", "handlers"])
def test_an_action_may_not_take_a_name_the_registry_uses(name: str) -> None:
    """`__getattr__` runs only when ordinary lookup fails, so `registry.add`
    would resolve to the method and a screen binding through it would fail far
    from the cause."""
    actions = Registry()

    def shadow(state: State, payload: Nothing) -> State:
        return state

    shadow.__name__ = name
    with pytest.raises(StateError, match="reserved"):
        actions(shadow)


def test_the_reserved_names_are_the_registry_s_own() -> None:
    from pycompose.state.actions import RESERVED

    assert {"add", "names", "dispatch", "register", "handlers"} <= RESERVED


def test_an_ordinary_action_name_is_still_fine() -> None:
    actions = Registry()

    @actions
    def delete_note(state: State, payload: Nothing) -> State:
        return state

    assert actions.delete_note is delete_note


def test_looking_an_action_up_is_a_direct_hit() -> None:
    """The index is built once at registration, not scanned per access."""
    actions = Registry()

    @actions
    def only(state: State, payload: Nothing) -> State:
        return state

    assert actions.__dict__["_by_name"]["only"] is only
