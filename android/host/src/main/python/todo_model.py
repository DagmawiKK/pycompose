"""Pure model layer of the todo sample app: its data and the selectors over it.

Nothing here can touch the host; the view model changes the data through these
and the screen reads it through them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

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


@dataclass(frozen=True)
class Task:
    """One task.

    Attributes:
        id: Stable identity, never reused.
        title: What to do.
        done: Whether it is finished.
    """

    id: int
    title: str
    done: bool = False


INITIAL: tuple[Task, ...] = (
    Task(1, "Read the PyCompose plan", done=True),
    Task(2, "Try the todo demo"),
)


def visible_tasks(tasks: tuple[Task, ...], selected: str) -> list[Task]:
    """Return the tasks the current filter admits, in their existing order.

    Args:
        tasks: Every task.
        selected: Active filter name.

    Returns:
        Tasks matching the filter; all of them when the filter is ``all``.
    """
    if selected == "active":
        return [task for task in tasks if not task.done]
    if selected == "done":
        return [task for task in tasks if task.done]
    return list(tasks)


def summary_for(tasks: tuple[Task, ...]) -> str:
    """Return the plain completion count shown under the heading.

    Args:
        tasks: Every task.

    Returns:
        Text naming how many tasks are active and how many are done.
    """
    done = sum(1 for task in tasks if task.done)
    return f"{len(tasks) - done} active, {done} done"
