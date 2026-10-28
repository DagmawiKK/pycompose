"""The app context: what a composition reaches without it being threaded.

This is the same bargain Compose strikes with ``LocalConfiguration.current``,
and the tests here check both halves of it -- that it fills what it should, and
that it stays out of everything else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pycompose import AppContext, composable, context, install_context
from pycompose.composition import expand
from pycompose.core.context import has_context
from pycompose.errors import IrValidationError
from pycompose.m3 import Text

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"


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
