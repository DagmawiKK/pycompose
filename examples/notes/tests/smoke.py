"""End-to-end walk through Notes, standing in for the Android host.

Run it with no device attached:

    python examples/notes/tests/smoke.py

It prints what a user would see at each step. Any failure raises.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main  # noqa: E402
from harness import Host, data, effects, titles  # noqa: E402


def show(step: str, host: Host, *extra: object) -> None:
    """Print what the user would be looking at after one step.

    Args:
        step: What was done.
        host: The session to read.
        *extra: Anything else worth printing.
    """
    snapshot = host.snapshot()
    route = data(snapshot)["route"]
    print(f"{step:<34} route={route:<8} notes={titles(snapshot)}", *extra)


def main_() -> None:
    host = Host(main)
    show("fresh install", host)

    host.tap("new_note", "new")
    show("tap New note", host, effects(host.snapshot()))

    host.tap("set_title", "title", value="Groceries")
    host.tap("set_body", "body", value="Milk\nBread\nCoffee")
    show("type title and body", host)

    host.tap("go_back", "back")
    show("back to the list", host, effects(host.snapshot()))

    host.tap("open_note", "n1")
    show("open Welcome", host, effects(host.snapshot()))

    host.lifecycle("onBackRequested")
    show("system back", host, effects(host.snapshot()))

    host.tap("delete_note", "n2")
    show("delete one note", host)

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
    host.tap("open_note", "n1")
    host.tap("set_title", "title", value="Half-typed")
    published = host.snapshot()["metadata"]["data"]

    revived = Host(main, route=published["route"], restore=_json(published))
    show("relaunch after process death", revived)
    print(f"{'  text survived':<34} {published['notes'][1]['title']!r}")
    assert revived.error == "", revived.error


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
