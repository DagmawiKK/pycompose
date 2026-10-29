"""The bundled demo app: add, complete, filter and delete through the runtime."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pycompose.bridge import runtime
from pycompose.contract.catalog import SCHEMA_VERSION

DEMO = Path(__file__).resolve().parents[1] / "android/host/src/main/python"


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Put the demo's directory where the worker finds it, and clean up after."""
    monkeypatch.syspath_prepend(str(DEMO))
    yield "main:app"
    runtime.close()
    for name in ("main", "todo_model"):
        sys.modules.pop(name, None)


def snapshot() -> dict[str, Any]:
    return json.loads(runtime.fetch_latest_snapshot())


def nodes(kind: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    pending = [snapshot()["root"]]
    while pending:
        node = pending.pop(0)
        if node["type"] == kind:
            found.append(node["props"])
        pending = node.get("children", []) + pending
    return found


def titles() -> list[str]:
    """The visible task titles, after the heading and summary."""
    return [text["text"] for text in nodes("Text")[2:]]


def summary() -> str:
    return nodes("Text")[1]["text"]


def intents() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if set(value) == {"fields", "intent"}:
                if value not in found:
                    found.append(value)
                return
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(snapshot()["root"])
    return found


def send(name: str, bound: dict[str, Any] | None = None, **payload: Any) -> None:
    """Deliver the tap on the control carrying intent class ``name``.

    Args:
        name: The intent's class name.
        bound: The fields the control binds, when several carry the class.
        **payload: The event's own fields.
    """
    (intent,) = (
        found
        for found in intents()
        if found["intent"].rpartition(".")[2] == name
        and (bound is None or found["fields"] == bound)
    )
    runtime.accept_action(json.dumps({**intent, "payload": payload}))


def effects() -> list[dict[str, Any]]:
    return snapshot().get("metadata", {}).get("effects", [])


def test_demo_builds_a_valid_snapshot_of_instance_scoped_intents(demo: str) -> None:
    runtime.start(demo, "", True)
    current = snapshot()
    assert current["schemaVersion"] == SCHEMA_VERSION
    contracts = {
        name.rpartition(".")[2]: contract["payload"]
        for name, contract in current["metadata"]["intents"].items()
    }
    assert contracts["SetDraft"] == {"value": {"required": True, "type": "string"}}
    assert contracts["ToggleTask"]["done"] == {"required": True, "type": "boolean"}
    assert contracts["SetFilter"]["value"]["values"] == ["all", "active", "done"]
    toggles = [i["fields"] for i in intents() if i["intent"].endswith(".ToggleTask")]
    assert toggles == [{"taskId": 1}, {"taskId": 2}]
    assert runtime.fetch_latest_error() == ""


def test_demo_effects_ride_the_add_snapshot_only(demo: str) -> None:
    runtime.start(demo, "", True)
    assert effects() == []
    send("SetDraft", value="Buy milk")
    assert effects() == []
    send("AddTask")
    assert effects() == [{"kind": "toast", "payload": {"message": 'Added "Buy milk"'}}]
    # The next intent publishes its own snapshot, so nothing replays.
    send("SetFilter", {"value": "active"})
    assert effects() == []


def test_demo_adds_completes_filters_and_deletes_tasks(demo: str) -> None:
    runtime.start(demo, "", True)
    assert summary() == "1 active, 1 done"
    assert titles() == ["Read the PyCompose plan", "Try the todo demo"]
    assert [(c["label"], c["selected"]) for c in nodes("FilterChip")] == [
        ("All", True),
        ("Active", False),
        ("Done", False),
    ]

    send("SetDraft", value="  Buy milk  ")
    assert nodes("TextField")[0]["value"] == "  Buy milk  "
    assert nodes("Button")[0]["enabled"]
    send("AddTask")
    assert titles() == ["Read the PyCompose plan", "Try the todo demo", "Buy milk"]
    assert nodes("TextField")[0]["value"] == ""
    assert not nodes("Button")[0]["enabled"]
    assert summary() == "2 active, 1 done"

    send("ToggleTask", {"taskId": 2}, done=True)
    assert [box["checked"] for box in nodes("Checkbox")] == [True, True, False]
    send("ToggleTask", {"taskId": 2}, done=False)
    assert [box["checked"] for box in nodes("Checkbox")] == [True, False, False]

    send("SetFilter", {"value": "active"})
    assert titles() == ["Try the todo demo", "Buy milk"]
    send("SetFilter", {"value": "done"})
    assert titles() == ["Read the PyCompose plan"]
    send("SetFilter", {"value": "active"})
    send("RemoveTask", {"taskId": 3})
    assert titles() == ["Try the todo demo"]
    assert runtime.fetch_latest_error() == ""


def test_demo_reports_empty_filters_without_crashing(demo: str) -> None:
    runtime.start(demo, "", True)
    send("SetFilter", {"value": "done"})
    assert titles() == ["Read the PyCompose plan"]
    send("RemoveTask", {"taskId": 1})
    assert titles() == ["Nothing finished yet."]


def test_demo_receives_the_resume_event(demo: str) -> None:
    runtime.start(demo, "", True)
    assert summary() == "1 active, 1 done"
    runtime.accept_action(json.dumps({"intent": "onResume", "payload": {}}))
    assert summary() == "resumed"
    assert runtime.fetch_latest_error() == ""


def test_demo_rejects_events_that_break_the_declared_contract(demo: str) -> None:
    runtime.start(demo, "", True)
    before = runtime.fetch_latest_snapshot()

    send("SetDraft", value=7)
    assert runtime.fetch_latest_snapshot() == before
    assert "invalid app action payload" in runtime.fetch_latest_error()

    send("AddTask", title="Sneaky")
    assert runtime.fetch_latest_snapshot() == before
    assert "invalid app action payload" in runtime.fetch_latest_error()


def test_demo_survives_process_death_by_restoring_saved_state(demo: str) -> None:
    runtime.start(demo, "", True)
    send("SetDraft", value="Survive rotation")
    send("AddTask")
    send("ToggleTask", {"taskId": 3}, done=True)
    send("SetFilter", {"value": "done"})
    shown = titles()

    # The host hands the published bytes straight back to a rebuilt process.
    saved = snapshot()["metadata"]["data"]
    runtime.close()
    runtime.start(demo, "", True, restore=json.dumps(saved))
    assert titles() == shown
    assert snapshot()["metadata"]["data"] == saved


def test_demo_boots_cleanly_from_data_it_cannot_use(demo: str) -> None:
    for unusable in ("", "not json", "[]", '{"stack": "no"}', '{"stack": [1, 2]}'):
        runtime.close()
        runtime.start(demo, "", True, restore=unusable)
        assert titles() == ["Read the PyCompose plan", "Try the todo demo"], unusable
        assert runtime.fetch_latest_error() == "", unusable
