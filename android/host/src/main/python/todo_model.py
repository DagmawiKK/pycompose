"""Pure model layer of the todo sample app: declared shape and selectors.

The state's declared shape (:data:`INITIAL`), its wire payload types and the
pure selectors the composables and actions share. Actions mutate through
these; nothing here can touch the host.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypedDict, cast

from pycompose.state import State
from pycompose.utils.json_canonical import thaw_json

Filter = Literal["all", "active", "done"]

FILTERS: tuple[tuple[Filter, str], ...] = (
    ("all", "All"),
    ("active", "Active"),
    ("done", "Done"),
)

EMPTY_MESSAGES: Mapping[str, str] = {
    "all": "Nothing on the list.",
    "active": "Nothing left to do.",
    "done": "Nothing finished yet.",
}

INITIAL: Mapping[str, Any] = {
    "tasks": [
        {"id": 1, "title": "Read the PyCompose plan", "done": True},
        {"id": 2, "title": "Try the todo demo", "done": False},
    ],
    "draft": "",
    "filter": "all",
    "summary": "1 active, 1 done",
}


class DraftPayload(TypedDict):
    value: str


class AddPayload(TypedDict):
    title: str


class TogglePayload(TypedDict):
    task_id: int
    done: bool


class RemovePayload(TypedDict):
    task_id: int


class FilterPayload(TypedDict):
    value: Filter


class ResumePayload(TypedDict):
    pass


class RoutePayload(TypedDict):
    route: str


class ConfigPayload(TypedDict):
    orientation: Literal["portrait", "landscape"]
    dark_mode: bool
    locale: str
    density: float


def model(state: State) -> dict[str, Any]:
    """Return the app's task model as ordinary mutable JSON values.

    Args:
        state: Current snapshot whose frozen data describes the screen.

    Returns:
        A detached copy the next transition may edit before freezing it again.
    """
    return cast("dict[str, Any]", thaw_json(state.data or {}))


def visible_tasks(tasks: list[Any], selected: str) -> list[Any]:
    """Return the tasks the current filter admits, in their existing order.

    Args:
        tasks: Every task in the model.
        selected: Active filter name.

    Returns:
        Tasks matching the filter; all of them when the filter is ``all``.
    """
    if selected == "active":
        return [task for task in tasks if not task["done"]]
    if selected == "done":
        return [task for task in tasks if task["done"]]
    return list(tasks)


def summary_for(tasks: list[Any]) -> str:
    """Return the plain completion count shown under the heading.

    Args:
        tasks: Every task in the model.

    Returns:
        Text naming how many tasks are active and how many are done.
    """
    done = sum(1 for task in tasks if task["done"])
    return f"{len(tasks) - done} active, {done} done"
