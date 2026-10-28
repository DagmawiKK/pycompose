"""End-to-end walk through Notes, standing in for the Android host.

Run it with no device attached:

    python examples/notes/tests/smoke.py

It prints what a user would see at each step, against storage of its own rather
than wherever the app's notes live when a device runs it. Any failure raises.
Process death is covered by ``tests/test_notes_example.py``.
"""

from __future__ import annotations

from pathlib import Path

from pycompose.testing.driver import AppDriver

ROOT = Path(__file__).resolve().parents[1]


def show(step: str, app: AppDriver) -> None:
    """Print the back stack and the texts on screen after one step.

    Args:
        step: What was done.
        app: The running app.
    """
    stack = app.snapshot()["metadata"]["data"]["stack"]
    routes = [entry["route"]["route"].rpartition(".")[2] for entry in stack]
    print(f"{step:<24} {' > '.join(routes):<26} {app.texts()[:4]}")


def main() -> None:
    with AppDriver(ROOT) as app:
        show("fresh install", app)

        app.click(type="FloatingActionButton")
        show("tap New note", app)

        title, body = (n["id"] for n in app.nodes() if n["type"] == "TextField")
        app.edit("Groceries", id=title)
        app.edit("Milk\nBread\nCoffee", id=body)
        show("type title and body", app)

        app.lifecycle("onBackRequested")
        show("system back", app)
        assert "Groceries" in app.texts(), app.texts()

        app.click(text="How this works", type="TextButton")
        show("tap How this works", app)

        app.click(text="Groceries")
        show("open the note", app)

        app.click(text="Delete note")
        show("delete the note", app)
        assert "Groceries" not in app.texts(), app.texts()
        assert app.failures == [], app.failures


if __name__ == "__main__":
    main()
