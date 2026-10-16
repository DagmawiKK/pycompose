"""The app context: what a composition reaches without it being threaded.

This is the same bargain Compose strikes with ``LocalConfiguration.current``,
and the tests here check both halves of it -- that it fills what it should, and
that it stays out of everything else.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, TypedDict

import pytest

from pycompose import AppContext, composable, context, install_context
from pycompose.composition import expand
from pycompose.core.context import has_context
from pycompose.errors import IrValidationError
from pycompose.m3 import Text

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"


class Nothing(TypedDict):
    pass


@pytest.fixture(autouse=True)
def _clean(request: pytest.FixtureRequest) -> None:
    """Leave no context installed, so one test cannot leak into the next.

    Args:
        request: The fixture request, used to schedule the teardown.

    Returns:
        None, once the teardown is scheduled.
    """
    request.addfinalizer(lambda: install_context(None))


# ---------------------------------------------------------------------------
# The context itself
# ---------------------------------------------------------------------------


def test_a_context_answers_attribute_access() -> None:
    install_context(AppContext(actions="registry", container="graph"))
    assert context().container == "graph"


def test_a_missing_name_says_what_is_there() -> None:
    install_context(AppContext(actions="registry"))
    with pytest.raises(AttributeError, match="holds actions"):
        _ = context().container


def test_no_context_is_a_named_failure_not_a_none() -> None:
    assert has_context() is False
    with pytest.raises(KeyError, match="outside a session"):
        context()


# ---------------------------------------------------------------------------
# What a composable may reach
# ---------------------------------------------------------------------------


def test_a_composable_reaches_the_context_without_being_told() -> None:
    install_context(AppContext(actions="from-context"))
    seen: list[Any] = []

    @composable
    def screen(*, actions: Any = None) -> Any:
        seen.append(actions)
        return Text(id="t", text="x")

    expand(screen(id="s"))
    assert seen == ["from-context"]


def test_an_explicit_value_always_wins() -> None:
    install_context(AppContext(actions="from-context"))
    seen: list[Any] = []

    @composable
    def screen(*, actions: Any = None) -> Any:
        seen.append(actions)
        return Text(id="t", text="x")

    expand(screen(id="s", actions="explicit"))
    assert seen == ["explicit"]


def test_an_explicit_none_is_filled_too() -> None:
    """There is no way to say 'deliberately nothing' for an ambient name."""
    install_context(AppContext(actions="from-context"))
    seen: list[Any] = []

    @composable
    def screen(*, actions: Any = None) -> Any:
        seen.append(actions)
        return Text(id="t", text="x")

    expand(screen(id="s", actions=None))
    assert seen == ["from-context"]


def test_a_name_the_context_does_not_carry_is_left_alone() -> None:
    """Otherwise a forgotten argument would be silently invented."""
    install_context(AppContext(actions="from-context"))

    @composable
    def screen(*, theme: str) -> Any:
        return Text(id="t", text=theme)

    with pytest.raises(IrValidationError, match="theme"):
        screen(id="s")


def test_a_composable_needs_no_context_when_none_is_installed() -> None:
    @composable
    def screen(*, label: str = "plain") -> Any:
        return Text(id="t", text=label)

    assert expand(screen(id="s")) is not None


# ---------------------------------------------------------------------------
# The real app, which is where the boilerplate went
# ---------------------------------------------------------------------------


def test_the_notes_screens_no_longer_take_a_registry_argument() -> None:
    """Callers omit it; the context supplies it."""
    sys.path.insert(0, str(APP))
    try:
        from notes_app.views import list_screen
    finally:
        sys.path.remove(str(APP))

    import inspect

    assert "actions" in inspect.signature(list_screen).parameters


def test_the_notes_snapshot_takes_no_registry() -> None:
    """It used to exist only to thread one down."""
    sys.path.insert(0, str(APP))
    try:
        from notes_app.view_model import snapshot
    finally:
        sys.path.remove(str(APP))

    import inspect

    assert "actions" not in inspect.signature(snapshot).parameters


def test_only_actions_that_reach_storage_still_declare_a_dependency() -> None:
    """Flipping a sheet open does not need the repository, and no longer says so."""
    import inspect

    sys.path.insert(0, str(APP))
    try:
        import notes_app.actions  # noqa: F401 -- registers the package
    finally:
        sys.path.remove(str(APP))

    definitions = sys.modules["notes_app.actions"]
    mutates = {"new_note", "open_note", "set_title", "set_body", "delete_note"}
    renders_only = {"go_back", "set_about", "on_route_changed", "on_config_changed"}

    for name in sorted(mutates | renders_only):
        handler = getattr(definitions, name)
        function = getattr(handler, "function", handler)
        wants = "notes" in inspect.signature(function).parameters
        assert wants is (name in mutates), name


def test_the_app_still_renders_with_a_context_installed() -> None:
    from pycompose.bridge import BridgeSurface
    from pycompose.state import Store

    sys.path.insert(0, str(APP))
    try:
        import main
        from notes_app.container import AppContainer
        from notes_app.data.notes_repo import MemoryNotesRepo
        from notes_app.domain import Notes
    finally:
        sys.path.remove(str(APP))

    supplied = AppContainer(Notes(MemoryNotesRepo([])))
    main.actions.install_container(supplied)
    install_context(
        AppContext(actions=main.actions, container=supplied, notes=supplied.notes)
    )
    surface = BridgeSurface(Store(main.build(container=supplied)), main.actions)
    assert surface.expose_latest_snapshot() is not None
