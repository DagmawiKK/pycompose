"""Todo entrypoint: one view model, its intents, and a screen drawn from its state.

Every task row binds its own task's id into its intents, so one intent class
serves all rows without the host ever holding a handler.
"""

from __future__ import annotations

from todo_model import (
    EMPTY_MESSAGES,
    FILTERS,
    INITIAL,
    Filter,
    Task,
    summary_for,
    visible_tasks,
)

from pycompose import composable
from pycompose.app import App, Destination, Intent, Toast, ViewModel
from pycompose.model.nodes import Node
from pycompose.state import AppState
from pycompose.ui import (
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


class Todo(AppState):
    """Everything the screen shows; saved across process death.

    Attributes:
        tasks: Every task, oldest first.
        draft: The input field's text.
        filter: Which tasks the list shows.
        resumed: Whether the app has come back to the foreground.
    """

    tasks: tuple[Task, ...] = INITIAL
    draft: str = ""
    filter: str = "all"
    resumed: bool = False


class SetDraft(Intent):
    value: str


class AddTask(Intent):
    title: str


class ToggleTask(Intent):
    task_id: int
    done: bool


class RemoveTask(Intent):
    task_id: int


class SetFilter(Intent):
    value: Filter


class TodoViewModel(ViewModel[Todo]):
    """The task list and what the user can do with it."""

    def __init__(self) -> None:
        super().__init__(Todo())

    def on_intent(self, intent: Intent) -> None:
        """Handle one intent from the screen.

        Args:
            intent: What the control asked for.
        """
        state = self.state
        match intent:
            case SetDraft(value=value):
                self.state = state.evolve(draft=value)
            case AddTask(title=title) if title.strip():
                highest = max((task.id for task in state.tasks), default=0)
                task = Task(highest + 1, title.strip())
                self.state = state.evolve(tasks=(*state.tasks, task), draft="")
                self.emit(Toast(f'Added "{task.title}"'))
            case ToggleTask(task_id=task_id, done=done):
                self.state = state.evolve(
                    tasks=tuple(
                        Task(t.id, t.title, done) if t.id == task_id else t
                        for t in state.tasks
                    )
                )
            case RemoveTask(task_id=task_id):
                kept = tuple(t for t in state.tasks if t.id != task_id)
                if kept != state.tasks:
                    self.state = state.evolve(tasks=kept)
            case SetFilter(value=value):
                self.state = state.evolve(filter=value)

    def on_resume(self) -> None:
        """Note the return to the foreground, proving the event arrived."""
        self.state = self.state.evolve(resumed=True)


@composable
def task_row(*, task: Task) -> Node:
    """Build one task line: its checkbox, title and remove control.

    Args:
        task: The task this row shows.

    Returns:
        A Row declaration carrying this task's intents.
    """
    return Row(
        id="row",
        vertical_alignment="centerVertically",
        modifier=Modifier().padding(4),
        children=[
            Checkbox(
                id="done",
                checked=task.done,
                on_checked_change=ToggleTask.bind(task_id=task.id),
            ),
            Text(
                text=task.title,
                style="bodyLarge",
                modifier=Modifier().fill_max_width(0.7),
            ),
            TextButton(
                id="remove", text="Delete", on_click=RemoveTask(task_id=task.id)
            ),
        ],
    )


def screen(state: Todo) -> Node:
    """Draw the whole screen from the view model's state.

    Args:
        state: The view model's state.

    Returns:
        A Scaffold declaration; every control carries an intent.
    """
    rows: list[Node] = [
        task_row(id=f"task_{task.id}", task=task)
        for task in visible_tasks(state.tasks, state.filter)
    ]
    if not rows:
        rows = [
            Text(
                text=EMPTY_MESSAGES.get(state.filter, EMPTY_MESSAGES["all"]),
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
                selected=state.filter == value,
                on_click=SetFilter(value=value),
            )
        )
    summary = "resumed" if state.resumed else summary_for(state.tasks)
    return Scaffold(
        id="screen",
        modifier=Modifier().padding(20).fill_max_width(),
        content=Column(
            id="body",
            children=[
                Text(text="Tasks", style="titleLarge"),
                Text(text=summary, style="bodySmall"),
                Spacer(modifier=Modifier().size(12)),
                Row(
                    id="entry",
                    vertical_alignment="centerVertically",
                    children=[
                        TextField(
                            id="draft",
                            value=state.draft,
                            label="New task",
                            on_value_change=SetDraft,
                            modifier=Modifier().fill_max_width(0.7),
                        ),
                        Spacer(modifier=Modifier().size(8)),
                        Button(
                            id="add",
                            text="Add",
                            enabled=bool(state.draft.strip()),
                            on_click=AddTask(title=state.draft.strip()),
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


app = App(start=Destination(lambda _container, _route: TodoViewModel(), screen))
