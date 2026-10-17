"""Todo entrypoint: worker-owned composition and app-declared actions.

Every task row targets its own instance through ``bind``, so one Python
transition serves all rows without the host ever holding a handler.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from todo_model import (
    EMPTY_MESSAGES,
    FILTERS,
    INITIAL,
    AddPayload,
    ConfigPayload,
    DraftPayload,
    FilterPayload,
    RemovePayload,
    ResumePayload,
    RoutePayload,
    TogglePayload,
    model,
    summary_for,
    visible_tasks,
)

from pycompose import action, composable
from pycompose.core import Node
from pycompose.core.effect import Effect
from pycompose.m3 import (
    Button,
    Checkbox,
    Column,
    FilterChip,
    LazyColumn,
    Modifier,
    Row,
    Scaffold,
    Spacer,
    Text,
    TextButton,
    TextField,
)
from pycompose.state import Actions, App, State


@composable
def task_row(*, task_id: int, title: str, done: bool) -> Node:
    """Build one task line: its checkbox, title and remove control.

    Args:
        task_id: Stable task identity, used for this row's bindings.
        title: Task text as shown to the user.
        done: Whether the task is complete.

    Returns:
        A Row declaration owning this instance's action bindings.
    """
    return Row(
        id="row",
        vertical_alignment="center",
        modifier=Modifier().padding(4),
        children=[
            Checkbox(
                id="done",
                checked=done,
                on_checked_change=toggle_task.bind(
                    id=f"task_{task_id}", task_id=task_id
                ),
            ),
            Text(
                text=title,
                style="bodyLarge",
                modifier=Modifier().fill_max_width(0.7),
            ),
            TextButton(
                id="remove",
                text="Delete",
                on_click=remove_task.bind(id=f"task_{task_id}", task_id=task_id),
            ),
        ],
    )


@composable
def todo_app(*, tasks: list[Any], draft: str, selected: str, summary: str) -> Node:
    """Build the whole screen from app data alone.

    Args:
        tasks: Every task in the model.
        draft: Current input field text.
        selected: Active filter name.
        summary: Status line, kept in the model so lifecycle events can own it.

    Returns:
        A Scaffold declaration; every control carries a data-only binding.
    """
    shown = visible_tasks(tasks, selected)
    rows: list[Node] = [
        task_row(
            id=f"task_{task['id']}",
            task_id=task["id"],
            title=task["title"],
            done=task["done"],
        )
        for task in shown
    ]
    if not rows:
        rows = [
            Text(
                text=EMPTY_MESSAGES[selected],
                style="bodyMedium",
                modifier=Modifier().padding(8),
            )
        ]
    chips: list[Node] = []
    for index, (value, label) in enumerate(FILTERS):
        if index:
            chips.append(Spacer(modifier=Modifier().size(8)))
        chips.append(
            FilterChip(
                id=value,
                label=label,
                selected=selected == value,
                on_click=set_filter.bind(id=value, value=value),
            )
        )
    return Scaffold(
        id="screen",
        modifier=Modifier().padding(20).fill_max_width(),
        content=Column(
            id="body",
            children=[
                Text(text="Tasks", style="titleLarge"),
                Text(
                    text=summary,
                    style="bodySmall",
                ),
                Spacer(modifier=Modifier().size(12)),
                Row(
                    id="entry",
                    vertical_alignment="center",
                    children=[
                        TextField(
                            id="draft",
                            value=draft,
                            label="New task",
                            on_value_change=set_draft.bind(id="draft"),
                            modifier=Modifier().fill_max_width(0.7),
                        ),
                        Spacer(modifier=Modifier().size(8)),
                        Button(
                            id="add",
                            text="Add",
                            enabled=bool(draft.strip()),
                            on_click=add_task.bind(id="add", title=draft.strip()),
                        ),
                    ],
                ),
                Spacer(modifier=Modifier().size(12)),
                Row(id="filters", children=chips),
                Spacer(modifier=Modifier().size(12)),
                LazyColumn(
                    id="tasks",
                    items=rows,
                    modifier=Modifier().fill_max_width(),
                ),
            ],
        ),
    )


def screen(
    current: Mapping[str, Any],
    version: int,
    effects: tuple[Effect, ...] = (),
) -> State:
    """Build the next snapshot from a task model.

    Args:
        current: Task model describing the screen to render.
        version: Monotonic app counter, incremented once per transition.
        effects: One-shot host requests to run once with this snapshot.

    Returns:
        A State whose root is a fresh declaration over this model.
    """
    return State(
        root=todo_app(
            id="todo",
            tasks=list(current["tasks"]),
            draft=str(current["draft"]),
            selected=str(current["filter"]),
            summary=str(current.get("summary", summary_for(current["tasks"]))),
        ),
        version=version,
        data=dict(current),
        effects=effects,
    )


@action
def set_draft(state: State, payload: DraftPayload) -> State:
    """Record the input field's current text.

    Args:
        state: Snapshot before the keystroke.
        payload: Event-supplied field text.

    Returns:
        The next snapshot with the draft updated.
    """
    next_model = model(state)
    next_model["draft"] = payload["value"]
    return screen(next_model, state.version + 1)


@action
def add_task(state: State, payload: AddPayload) -> State:
    """Append a task from the bound title and clear the input field.

    Args:
        state: Snapshot before the tap.
        payload: Title bound by the add button.

    Returns:
        The next snapshot, or the same one for an empty title.
    """
    title = payload["title"].strip()
    if not title:
        return state
    next_model = model(state)
    tasks = list(next_model["tasks"])
    highest = max((task["id"] for task in tasks), default=0)
    tasks.append({"id": highest + 1, "title": title, "done": False})
    next_model["tasks"] = tasks
    next_model["summary"] = summary_for(tasks)
    next_model["draft"] = ""
    return screen(
        next_model,
        state.version + 1,
        effects=(Effect("toast", {"message": f'Added "{title}"'}),),
    )


@action
def toggle_task(state: State, payload: TogglePayload) -> State:
    """Mark one task complete or reopened from its checkbox event.

    Args:
        state: Snapshot before the toggle.
        payload: Bound task id plus the checkbox's new value.

    Returns:
        The next snapshot with that task's completion set to the event value.
    """
    next_model = model(state)
    next_model["tasks"] = [
        {**task, "done": payload["done"]} if task["id"] == payload["task_id"] else task
        for task in next_model["tasks"]
    ]
    return screen(next_model, state.version + 1)


@action
def remove_task(state: State, payload: RemovePayload) -> State:
    """Delete one task by its bound id.

    Args:
        state: Snapshot before the tap.
        payload: Task id bound by that row's delete control.

    Returns:
        The next snapshot without the task.
    """
    next_model = model(state)
    next_model["tasks"] = [
        task for task in next_model["tasks"] if task["id"] != payload["task_id"]
    ]
    return screen(next_model, state.version + 1)


@action
def set_filter(state: State, payload: FilterPayload) -> State:
    """Switch the list filter.

    Args:
        state: Snapshot before the chip tap.
        payload: Filter name bound by the chip.

    Returns:
        The next snapshot showing the selected filter.
    """
    next_model = model(state)
    next_model["filter"] = payload["value"]
    return screen(next_model, state.version + 1)


def replace_root(state: State, text: str) -> State:
    """Rebuild the screen's summary line, leaving the task list untouched.

    Args:
        state: Current snapshot.
        text: New summary text.

    Returns:
        The next snapshot.
    """
    next_model = model(state)
    next_model["summary"] = text
    return screen(next_model, state.version + 1)


def view(restore: str) -> State:
    """Create the first snapshot, rehydrating whatever the host saved.

    This app keeps its state as ordinary JSON rather than a session shell, so
    it owns its own restore dance and the entry object hands it the host's
    bytes untouched.

    Args:
        restore: Canonical JSON of the previous snapshot's app data, or empty
            on a first run. Only the host's own bytes are ever handed back.

    Returns:
        The first todo screen, restored when the host supplied app data.
    """
    return screen(rehydrated(restore), 0)


app: App[Any] = App(view=view)


def rehydrated(restore: str) -> dict[str, Any]:
    """Return the starting task model, preferring saved data when present.

    Args:
        restore: Canonical JSON previously published in snapshot metadata.

    Returns:
        The saved model, or the initial one when nothing usable was restored.
    """
    if not restore:
        return dict(INITIAL)
    try:
        saved = json.loads(restore)
    except ValueError:
        return dict(INITIAL)
    if not isinstance(saved, dict):
        return dict(INITIAL)
    restored = {**dict(INITIAL), **saved}
    # The host only ever hands back bytes this app published, so anything
    # unusable here means the save is corrupt. Degrade, never crash on boot.
    restored["tasks"] = _usable_tasks(restored.get("tasks"))
    return restored


def _usable_tasks(tasks: object) -> list[dict[str, Any]]:
    """Keep only the saved tasks this app can actually render.

    Args:
        tasks: Whatever the saved model held under its task list.

    Returns:
        Well formed task dicts, or the initial list when none survived.
    """
    if not isinstance(tasks, list):
        return list(INITIAL["tasks"])
    kept = [
        task
        for task in tasks
        if isinstance(task, dict)
        and isinstance(task.get("id"), int)
        and isinstance(task.get("title"), str)
        and isinstance(task.get("done"), bool)
    ]
    # An empty list is a deliberate "no tasks left". A non-empty list that
    # yielded nothing renderable is a corrupt save, not an emptied app.
    return kept or (list(INITIAL["tasks"]) if tasks else [])


@action
def on_route_changed(state: State, payload: RoutePayload) -> State:  # noqa: ARG001
    """Accept a route change from the host.

    The host echoes every route change back as an ordinary action rather than
    rebuilding Python, which is what keeps an app's session alive across
    navigation. This app has a single screen, so there is only one destination
    and every route resolves to it.

    Args:
        state: Snapshot before the route change.
        payload: The destination the host is now showing.

    Returns:
        The same screen, redrawn for the new route.
    """
    return screen(model(state), state.version + 1)


@action
def on_resume(state: State, payload: ResumePayload) -> State:  # noqa: ARG001
    """Show the device's own configuration on return, proving it arrived.

    Args:
        state: Snapshot before the app came back to the foreground.
        payload: Empty payload; the host sends nothing extra.

    Returns:
        The next snapshot with the configuration line filled in.
    """
    return replace_root(state, "resumed")


@action
def on_config_changed(state: State, payload: ConfigPayload) -> State:
    """React to configuration facts only Python cannot observe itself.

    Args:
        state: Snapshot before the configuration changed.
        payload: Orientation, dark mode, locale and density from the host.

    Returns:
        The next snapshot describing the current configuration.
    """
    return replace_root(
        state,
        f"{payload['orientation']}, {'dark' if payload['dark_mode'] else 'light'}, "
        f"{payload['locale']} @ {payload['density']:g}x",
    )


actions = Actions(
    on_route_changed,
    set_draft,
    add_task,
    toggle_task,
    remove_task,
    set_filter,
    on_resume,
    on_config_changed,
)
