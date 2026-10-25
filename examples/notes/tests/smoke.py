"""End-to-end walk through Notes, standing in for the Android host.

Run it with no device attached:

    python examples/notes/tests/smoke.py

It prints what a user would see at each step, against a store of its own rather
than wherever the app's notes live when a device runs it. Any failure raises.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from harness import Host, data, effects  # noqa: E402

from pycompose.repository import use_root  # noqa: E402


def show(step: str, host: Host, *extra: object) -> None:
    """Print what the user would be looking at after one step.

    Args:
        step: What was done.
        host: The session to read.
        *extra: Anything else worth printing.
    """
    snapshot = host.snapshot()
    route = data(snapshot)["route"]
    print(f"{step:<34} route={route:<8} notes={host.titles}", *extra)


def main_() -> None:
    # A store of its own: notes outlive the process, so a file left behind by a
    # previous run would make "fresh install" a lie, and writing to the working
    # directory would leave one behind.
    use_root(Path(tempfile.mkdtemp(prefix="notes-smoke-")))

    host = Host(main)
    show("fresh install", host)

    host.tap("new_note")
    show("tap New note", host, effects(host.snapshot()))

    host.tap("set_title", value="Groceries")
    host.tap("set_body", value="Milk\nBread\nCoffee")
    show("type title and body", host)

    host.tap("go_back")
    show("back to the list", host, effects(host.snapshot()))

    # The button binds the value it wants, so the host sends no payload for it.
    host.tap("set_about", {"open": True})
    show("tap How this works", host, f"aboutOpen={data(host.snapshot())['aboutOpen']}")

    # The sheet reports what it settled on, as after a swipe. This binding names
    # no value, so the event is the one that carries it -- and the app assigns
    # it rather than toggling what it believed.
    host.tap("set_about", {}, open=False)
    show(
        "swipe the sheet away", host, f"aboutOpen={data(host.snapshot())['aboutOpen']}"
    )

    host.tap("open_note", {"note_id": 1})
    show("open the note", host, effects(host.snapshot()))

    host.lifecycle("onBackRequested")
    show("system back", host, effects(host.snapshot()))

    host.lifecycle(
        "onConfigChanged",
        darkMode=True,
        orientation="portrait",
        locale="en-US",
        density=2.0,
    )
    background = host.snapshot()["root"]["props"]["containerColor"]
    print(f"{'switch to dark mode':<34} background={background}")

    # The half-typed-text case: kill the process mid-sentence.
    host.tap("open_note", {"note_id": 1})
    host.tap("set_title", value="Half-typed")
    published = host.snapshot()["metadata"]["data"]

    revived = Host(main, route=published["route"], restore=_json(published))
    show("relaunch after process death", revived)
    assert "Half-typed" in revived.titles, revived.titles
    print(f"{'  text survived':<34} {revived.titles!r}")
    assert revived.error == "", revived.error

    revived.tap("go_back")
    revived.tap("delete_note", {"note_id": 1})
    show("delete the note", revived)


def _json(value: object) -> str:
    """Return this value as the canonical JSON the host would hand back.

    Args:
        value: The app data a snapshot published.

    Returns:
        JSON text.
    """
    import json

    return json.dumps(value)


if __name__ == "__main__":
    main_()
