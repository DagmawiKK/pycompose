"""What the check asserts about the sample, and the steps that drive it."""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import zipfile
from pathlib import Path

from tools.phone_check.device import (
    Bounds,
    Device,
    Node,
    PhoneCheckError,
    changed,
    frames_until_settled,
)

ROOT = Path(__file__).resolve().parents[2]
"""The repository, whose sample and tooling this drives."""

APP = ROOT / "examples/notes"
"""The sample the check drives: two screens, a spring and a scroll."""

ACTIVITY = "com.pycompose.host.MainActivity"
"""The host's activity, in the package the app's ``applicationId`` names."""

TIME_PASSES = "pycompose.timePasses"
"""The launch extra that turns the pass log on, which a release build needs."""

TITLE_TEXT = "Groceries"
"""The first note's title: what the check types and then taps."""

BODY = " ".join(["A long note body that wraps over several lines."] * 16)
"""The first note's body: long enough that the editor has to scroll, and
that a short drag is a small part of its whole range."""

CHUNK = 150
"""How much of a long text is typed between pauses: a field drops keystrokes
that arrive faster than it can compose them, and a short body then fits on
screen, so there is nothing left to scroll."""

DEBUG_KEYSTORE = Path.home() / ".android/debug.keystore"
"""AGP's own debug key, present on any machine that has built an Android app."""


def step(message: str) -> None:
    """Say what is being checked.

    Args:
        message: The step's name.
    """
    print(f"\n== {message}")


def check(holds: bool, message: str) -> None:
    """Require one fact and say how it went.

    Args:
        holds: The fact.
        message: What it claims.

    Raises:
        PhoneCheckError: When it does not hold.
    """
    print(f"   {'ok  ' if holds else 'FAIL'}  {message}")
    if not holds:
        raise PhoneCheckError(message)


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    """Run one command in a working directory.

    Args:
        command: The program and its arguments.
        cwd: Where to run it.
        env: The environment to run it in.

    Raises:
        PhoneCheckError: When it exits nonzero, quoting its last words.
    """
    done = subprocess.run(command, cwd=cwd, env=env, capture_output=True, check=False)
    if done.returncode != 0:
        output = (done.stderr or done.stdout).decode(errors="replace").strip()
        raise PhoneCheckError(f"{' '.join(command)} failed:\n{output[-2000:]}")


def cli() -> Path:
    """Find the ``pycompose`` command beside the running interpreter.

    Returns:
        The command, or the one on ``PATH``.

    Raises:
        PhoneCheckError: When neither exists.
    """
    beside = Path(sys.executable).with_name("pycompose")
    found = beside if beside.is_file() else shutil.which("pycompose")
    if found is None:
        raise PhoneCheckError("no pycompose command")
    return Path(found)


def build(app: Path, work: Path) -> Path:
    """Build the app's release APK from a signed copy of it.

    Args:
        app: The app's directory, left untouched.
        work: Where to copy it and build.

    Returns:
        The APK.

    Raises:
        PhoneCheckError: When the keystore or the build output is missing.
    """
    if not DEBUG_KEYSTORE.is_file():
        raise PhoneCheckError(f"no debug keystore at {DEBUG_KEYSTORE}")
    copy = work / app.name
    shutil.copytree(
        app,
        copy,
        ignore=shutil.ignore_patterns(".pycompose", "__pycache__", "*_cache", "*.pyc"),
    )
    config = copy / "pycompose.toml"
    text = config.read_text()
    for key, value in {
        "keystore": str(DEBUG_KEYSTORE),
        "key_alias": "androiddebugkey",
        "store_password_env": "PYCOMPOSE_STORE_PASSWORD",
        "key_password_env": "PYCOMPOSE_KEY_PASSWORD",
    }.items():
        text = re.sub(rf"(?m)^{key} = .*$", f'{key} = "{value}"', text)
    config.write_text(text)
    env = {
        **os.environ,
        "PYCOMPOSE_STORE_PASSWORD": "android",
        "PYCOMPOSE_KEY_PASSWORD": "android",
    }
    run([str(cli()), "build", "apk", "--release"], cwd=copy, env=env)
    outputs = copy / ".pycompose/android/host/build/outputs/apk/release"
    found = list(outputs.glob("*.apk"))
    if len(found) != 1:
        raise PhoneCheckError(f"expected one release APK, found {found}")
    return found[0]


def sources_in(apk: Path) -> list[str]:
    """List every Python source the APK packages, at any depth.

    Args:
        apk: The artifact.

    Returns:
        One entry per ``.py`` file found, named by the archive that holds it.
    """
    found = []
    with zipfile.ZipFile(apk) as outer:
        for name in outer.namelist():
            if name.endswith(".py"):
                found.append(name)
            if name.endswith((".imy", ".zip")):
                with zipfile.ZipFile(io.BytesIO(outer.read(name))) as inner:
                    found.extend(
                        f"{name}!{entry}"
                        for entry in inner.namelist()
                        if entry.endswith(".py")
                    )
    return found


def application_id(app: Path) -> str:
    """Read the app's application id.

    Args:
        app: The app's directory.

    Returns:
        The id its ``pycompose.toml`` states.
    """
    with (app / "pycompose.toml").open("rb") as handle:
        return str(tomllib.load(handle)["app"]["application_id"])


def launch(device: Device, apk: Path, package: str) -> None:
    """Install the APK fresh and start the app with the pass log on.

    Args:
        device: The device.
        apk: The artifact.
        package: The application id.
    """
    device.adb("uninstall", package, ignore=True)
    device.adb("install", "-r", str(apk))
    device.shell(
        "am", "start", "-W", "-n", f"{package}/{ACTIVITY}", "--ez", TIME_PASSES, "true"
    )
    device.wait_for("No notes yet.", timeout=120)


def require(
    device: Device,
    *,
    text: str | None = None,
    desc: str | None = None,
    nodes: list[Node] | None = None,
) -> Bounds:
    """Find a node, or say what is missing.

    Args:
        device: The device.
        text: The node's text, exactly.
        desc: The node's accessibility description, exactly.
        nodes: A dump to search, or None to take a fresh one.

    Returns:
        Its rectangle.

    Raises:
        PhoneCheckError: When nothing matches.
    """
    found = device.find(text=text, desc=desc, nodes=nodes)
    if found is None:
        raise PhoneCheckError(f"no node with text={text!r} desc={desc!r}")
    return found


def fields(device: Device, nodes: list[Node] | None = None) -> list[Bounds]:
    """Return the screen's editable fields, top to bottom.

    Args:
        device: The device.
        nodes: A dump to search, or None to take a fresh one.

    Returns:
        One rectangle per text field.

    Raises:
        PhoneCheckError: When nothing on screen can take a keystroke.
    """
    found = [node.bounds for node in nodes or device.nodes() if node.kind == "EditText"]
    if not found:
        raise PhoneCheckError("no editable field on screen")
    return found


def hide_keyboard(device: Device) -> None:
    """Press back until the keyboard is out of the way.

    A back press is only spent on the keyboard while the input method is
    showing; once it is not, the caller's next press reaches the screen.

    Args:
        device: The device.

    Raises:
        PhoneCheckError: When the keyboard will not go away.
    """
    for _ in range(3):
        if not device.keyboard_shown():
            return
        device.key(4)
        time.sleep(0.8)
    raise PhoneCheckError("the keyboard would not go away")


def fill_body(device: Device, text: str) -> None:
    """Type a long text into the focused field, in settled chunks.

    Args:
        device: The device, on a screen with a focused text field.
        text: What to type.
    """
    for start in range(0, len(text), CHUNK):
        device.type_text(text[start : start + CHUNK])
        time.sleep(0.35)


def add_note(device: Device, title: str) -> None:
    """Create one note and come back to the list.

    Args:
        device: The device.
        title: What to name it.
    """
    device.tap(*require(device, desc="New note").center)
    device.tap(*device.wait_for("Title").center)
    device.type_text(title)
    hide_keyboard(device)
    device.key(4)
    device.wait_for("Show note previews")


def springs(device: Device) -> None:
    """Toggle previews and watch the rows ease with no Python per frame.

    A spring is the one thing a device shows and a unit test only predicts: the
    rows must pass through heights that are neither the old nor the new one,
    and every one of those frames must come from the host.

    Args:
        device: The device, on the list screen with a note to show.

    Raises:
        PhoneCheckError: When the rows jump, or Python runs per frame.
    """
    step("a spring eases the rows, and only the host draws the frames")
    density = device.density
    header = device.wait_for("How this works")
    area = (0, header.bottom + 20 * density, device.size()[0], 590 * density)
    for attempt in range(2):
        switch = device.find(checkable=True)
        if switch is None:
            raise PhoneCheckError("no switch to toggle previews with")
        device.clear_log()
        before = device.shot().crop(area)
        device.tap(*switch.center)
        frames = frames_until_settled(device, area)
        time.sleep(0.5)
        passes = device.passes()
        check(1 <= passes <= 3, f"the toggle took {passes} pass(es), not one per frame")
        check(changed(frames[-1], before) > 400, "the rows reached their new height")
        eased = [frame for frame in frames[:-1] if changed(frame, frames[-1]) > 200]
        print(f"   ..    {len(eased)} intermediate frame(s) of {len(frames)} captured")
        if eased:
            check(True, "the rows eased through an intermediate height")
            return
        if attempt == 0:
            print("   ..    none caught; toggling back to look again")
    raise PhoneCheckError("the rows jumped: no intermediate height was ever drawn")


def to_top(device: Device) -> None:
    """Scroll the editor back to its first line.

    Typing a body scrolls the field into view as the caret runs down it, so the
    column is already somewhere else by the time the check starts measuring.

    Args:
        device: The device, on a screen with a scrollable column.
    """
    height = device.size()[1]
    for _ in range(4):
        device.drag(int(height * 0.25), int(height * 0.95), millis=400)
    time.sleep(1.0)


def follows(device: Device) -> None:
    """Drag the editor and watch the title follow, with Python idle.

    The title's offset is a layout-phase binding over the column's progress, so
    it moves while laying out: the check compares how far it moved with how far
    the field below it moved, and counts passes across the gesture. A title that
    does not follow, or a Python pass mid-drag, fails with ``PhoneCheckError``.

    Args:
        device: The device, on the list screen.
    """
    step("a layout-phase follow, with no Python pass while the finger moves")
    density = device.density
    height = device.size()[1]
    device.tap(*require(device, text=TITLE_TEXT).center)
    device.wait_for("Note")
    device.tap(*fields(device)[-1].center)
    fill_body(device, BODY)
    hide_keyboard(device)
    to_top(device)
    # The title's bottom edge stays in the tree while its upper half is clipped
    # by the column, and its height does not change, so the bottom is the edge
    # that reports where the field was laid out.
    rest = device.nodes()
    rest_title = require(device, text=TITLE_TEXT, nodes=rest)
    rest_body = fields(device, rest)[-1]
    device.clear_log()
    device.drag(int(height * 0.7), int(height * 0.7) - 110, millis=1200)
    time.sleep(0.6)
    moved = device.nodes()
    moved_title = require(device, text=TITLE_TEXT, nodes=moved)
    scrolled = rest_body.top - fields(device, moved)[-1].top
    shifted = rest_title.bottom - moved_title.bottom
    check(scrolled > 10 * density, f"the column scrolled {scrolled}px")
    check(
        shifted - scrolled > 5 * density,
        f"the title moved {shifted}px while the column moved {scrolled}px",
    )
    check(device.passes() == 0, "no Python pass ran while the column scrolled")
    device.clear_log()
    device.drag(int(height * 0.3), int(height * 0.85), millis=800)
    time.sleep(0.8)
    back = require(device, text=TITLE_TEXT)
    check(device.passes() == 0, "no Python pass ran while it scrolled back")
    check(
        abs(back.bottom - rest_title.bottom) <= 2 * density,
        "the title returned to its rest position",
    )


def drive(app: Path, apk: Path | None, device: Device, work: Path) -> None:
    """Build the APK if need be, then run every step against the device.

    Args:
        app: The app's directory.
        apk: An artifact to check, or None to build one.
        device: The device.
        work: Where a build may happen.
    """
    artifact = apk or build(app, work)
    missing = sources_in(artifact)
    check(
        not missing, f"{artifact.name} packages no Python source, {len(missing)} found"
    )
    launch(device, artifact, application_id(app))
    add_note(device, TITLE_TEXT)
    springs(device)
    follows(device)
