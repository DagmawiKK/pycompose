"""The bundled demo app: add, complete, filter and delete through the bridge."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pycompose.bridge import BridgeSurface
from pycompose.core.props import to_camel_case
from pycompose.state import Store

DEMO = (
    Path(__file__).resolve().parents[1]
    / "android"
    / "host"
    / "src"
    / "main"
    / "python"
    / "main.py"
)


@pytest.fixture(scope="module")
def demo() -> ModuleType:
    """Import the bundled demo app exactly as the Android worker does.

    Returns:
        The demo module, loaded from its on-device path.
    """
    spec = importlib.util.spec_from_file_location("pycompose_demo_main", DEMO)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


class Screen:
    """Read-only view over the latest demo snapshot, by component type."""

    def __init__(self, bridge: BridgeSurface) -> None:
        self._bridge = bridge

    def _nodes(self, kind: str) -> list[dict[str, Any]]:
        source = self._bridge.expose_latest_snapshot()
        assert source is not None
        found: list[dict[str, Any]] = []
        pending = [json.loads(source)["root"]]
        while pending:
            node = pending.pop(0)
            if node["type"] == kind:
                found.append(node["props"])
            pending = node.get("children", []) + pending
        return found

    def titles(self) -> list[str]:
        """Return the visible task titles in order.

        Returns:
            Task titles, excluding the screen heading.
        """
        return [text["text"] for text in self._nodes("Text")[2:]]

    def heading(self) -> list[str]:
        """Return the screen's own text lines.

        Returns:
            Title and summary text.
        """
        return [text["text"] for text in self._nodes("Text")[:2]]

    def filters(self) -> list[tuple[str, bool]]:
        """Return each filter chip's label and selection state.

        Returns:
            Label and selected pairs in declaration order.
        """
        return [(chip["label"], chip["selected"]) for chip in self._nodes("FilterChip")]

    def checked(self) -> list[bool]:
        """Return each visible task's checkbox value.

        Returns:
            Checkbox values in list order.
        """
        return [box["checked"] for box in self._nodes("Checkbox")]

    def draft(self) -> str:
        """Return the input field's current text.

        Returns:
            The draft title.
        """
        return self._nodes("TextField")[0]["value"]

    def add_enabled(self) -> bool:
        """Return whether the add control accepts a tap.

        Returns:
            The add button's enabled flag.
        """
        return bool(self._nodes("Button")[0]["enabled"])


def send(bridge: BridgeSurface, handler: Any, instance: str, **payload: Any) -> None:
    """Deliver one host action envelope the way the Android renderer does.

    Args:
        bridge: Surface owning the demo session.
        handler: App action whose bound values name this control's instance.
        instance: Stable instance key passed to the action's bind method.
        **payload: Event fields; bindings supply their own fixed values.
    """
    action_id = f"app.{handler.name}.{instance}"
    bridge.accept_action(json.dumps({"actionId": action_id, "payload": payload}))


def test_demo_builds_a_valid_snapshot_of_instance_scoped_bindings(
    demo: ModuleType,
) -> None:
    state = demo.build()
    bridge = BridgeSurface(Store(state), demo.actions)
    snapshot = json.loads(bridge.expose_latest_snapshot() or "{}")
    bindings = snapshot["metadata"]["actionBindings"]
    add = f"app.{demo.add_task.name}.add"
    draft = f"app.{demo.set_draft.name}.draft"
    toggle = f"app.{demo.toggle_task.name}.task_1"
    done = f"app.{demo.set_filter.name}.done"
    assert snapshot["schemaVersion"] == "1.7.0"
    assert bindings[add]["bound"] == {"title": ""}
    assert bindings[draft]["bound"] == {}
    assert bindings[draft]["payload"] == {"value": {"required": True, "type": "string"}}
    assert bindings[toggle]["bound"] == {"taskId": 1}
    assert bindings[toggle]["payload"]["done"] == {"required": True, "type": "boolean"}
    assert bindings[done]["bound"] == {"value": "done"}
    assert bindings[done]["payload"]["value"]["values"] == [
        "all",
        "active",
        "done",
    ]
    assert bridge.expose_latest_error() == ""


def test_demo_effects_ride_the_add_snapshot_only(demo: ModuleType) -> None:
    bridge = BridgeSurface(Store(demo.build()), demo.actions)

    def effects() -> list[dict]:
        snapshot = json.loads(bridge.expose_latest_snapshot() or "{}")
        return snapshot.get("metadata", {}).get("effects", [])

    assert effects() == []
    send(bridge, demo.set_draft, "draft", value="Buy milk")
    assert effects() == []
    send(bridge, demo.add_task, "add")
    assert effects() == [{"kind": "toast", "payload": {"message": 'Added "Buy milk"'}}]
    # The next transition publishes its own snapshot, so nothing replays.
    send(bridge, demo.set_filter, "active")
    assert effects() == []


def test_demo_adds_completes_filters_and_deletes_tasks(demo: ModuleType) -> None:
    bridge = BridgeSurface(Store(demo.build()), demo.actions)
    screen = Screen(bridge)
    assert screen.heading() == ["Tasks", "1 active, 1 done"]
    assert screen.titles() == ["Read the PyCompose plan", "Try the todo demo"]
    assert screen.filters() == [("All", True), ("Active", False), ("Done", False)]

    send(bridge, demo.set_draft, "draft", value="  Buy milk  ")
    assert screen.draft() == "  Buy milk  "
    assert screen.add_enabled()
    send(bridge, demo.add_task, "add")
    assert screen.titles() == [
        "Read the PyCompose plan",
        "Try the todo demo",
        "Buy milk",
    ]
    assert screen.draft() == ""
    assert not screen.add_enabled()
    assert screen.heading() == ["Tasks", "2 active, 1 done"]

    send(bridge, demo.toggle_task, "task_2", done=True)
    assert screen.checked() == [True, True, False]
    send(bridge, demo.toggle_task, "task_2", done=False)
    assert screen.checked() == [True, False, False]

    send(bridge, demo.set_filter, "active")
    assert screen.filters() == [("All", False), ("Active", True), ("Done", False)]
    assert screen.titles() == ["Try the todo demo", "Buy milk"]
    send(bridge, demo.set_filter, "done")
    assert screen.titles() == ["Read the PyCompose plan"]
    send(bridge, demo.set_filter, "active")
    send(bridge, demo.remove_task, "task_3")
    assert screen.titles() == ["Try the todo demo"]
    assert bridge.expose_latest_error() == ""


def test_demo_reports_empty_filters_without_crashing(demo: ModuleType) -> None:
    bridge = BridgeSurface(Store(demo.build()), demo.actions)
    screen = Screen(bridge)
    send(bridge, demo.set_filter, "done")
    assert screen.titles() == ["Read the PyCompose plan"]
    send(bridge, demo.remove_task, "task_1")
    assert screen.titles() == ["Nothing finished yet."]


def send_lifecycle(bridge: BridgeSurface, handler: Any, **payload: Any) -> None:
    """Deliver a host-initiated lifecycle event the way the activity does.

    Args:
        bridge: Surface owning the demo session.
        handler: The app action the host names by its bare camelCase alias.
        **payload: Event fields declared by the lifecycle contract.
    """
    action_id = to_camel_case(handler.name.rpartition(".")[2])
    bridge.accept_action(json.dumps({"actionId": action_id, "payload": payload}))


def test_demo_receives_host_lifecycle_events_by_their_camel_case_name(
    demo: ModuleType,
) -> None:
    bridge = BridgeSurface(Store(demo.build()), demo.actions)
    screen = Screen(bridge)

    def summary() -> str:
        return screen.heading()[1]

    assert summary() == "1 active, 1 done"
    send_lifecycle(
        bridge,
        demo.on_config_changed,
        darkMode=True,
        locale="fr-FR",
        density=3.0,
        orientation="landscape",
    )
    assert summary() == "landscape, dark, fr-FR @ 3x"
    send_lifecycle(bridge, demo.on_resume)
    assert summary() == "resumed"
    assert bridge.expose_latest_error() == ""


def test_demo_rejects_events_that_break_the_declared_contract(
    demo: ModuleType,
) -> None:
    bridge = BridgeSurface(Store(demo.build()), demo.actions)
    screen = Screen(bridge)
    before = bridge.expose_latest_snapshot()

    send(bridge, demo.set_draft, "draft", value=7)
    assert bridge.expose_latest_snapshot() == before

    send(bridge, demo.add_task, "add", title="Sneaky")
    assert bridge.expose_latest_snapshot() == before

    send(bridge, demo.remove_task, "task_99")
    assert bridge.expose_latest_snapshot() == before
    assert screen.titles() == ["Read the PyCompose plan", "Try the todo demo"]
    assert bridge.expose_latest_error()


def test_demo_survives_process_death_by_rehydrating_saved_data(
    demo: ModuleType,
) -> None:
    first = BridgeSurface(Store(demo.build()), demo.actions)
    screen = Screen(first)
    send(first, demo.set_draft, "draft", value="Survive rotation")
    send(first, demo.add_task, "add")
    send(first, demo.toggle_task, "task_3", done=True)
    assert screen.titles() == [
        "Read the PyCompose plan",
        "Try the todo demo",
        "Survive rotation",
    ]

    # The host hands the published bytes straight back to a rebuilt process.
    saved = json.loads(first.expose_latest_snapshot())["metadata"]["data"]
    rebuilt = BridgeSurface(Store(demo.build(restore=json.dumps(saved))), demo.actions)
    after = Screen(rebuilt)
    assert after.titles() == screen.titles()
    assert after.heading()[1] == screen.heading()[1]
    # The restored filter and draft come back too, not just the task list.
    assert json.loads(rebuilt.expose_latest_snapshot())["metadata"]["data"] == saved


def test_demo_boots_cleanly_from_data_it_cannot_use(demo: ModuleType) -> None:
    for unusable in ("", "not json", "[]", '{"tasks": "no"}', '{"tasks": [1, 2]}'):
        rebuilt = BridgeSurface(Store(demo.build(restore=unusable)), demo.actions)
        assert Screen(rebuilt).titles() == [
            "Read the PyCompose plan",
            "Try the todo demo",
        ], unusable
        assert rebuilt.expose_latest_error() == "", unusable


def test_demo_keeps_the_rendersable_tasks_from_a_partly_corrupt_save(
    demo: ModuleType,
) -> None:
    saved = json.dumps(
        {
            "tasks": [
                {"id": 1, "title": "Good", "done": False},
                {"id": "no number", "title": "Bad", "done": False},
                {"id": 2, "title": "Also good", "done": True},
            ],
        }
    )
    rebuilt = BridgeSurface(Store(demo.build(restore=saved)), demo.actions)
    assert Screen(rebuilt).titles() == ["Good", "Also good"]
