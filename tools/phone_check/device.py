"""One attached device, driven through adb: taps, drags, type, screenshots.

Nothing here knows what is being checked: it moves a finger, reads the
accessibility tree, and counts the passes the host logs.
"""

from __future__ import annotations

import io
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from PIL import Image, ImageChops

PASS_TAG = "PyCompose.pass"
"""The logcat tag of one Python pass, on in a release build only when asked."""

DUMP = "/sdcard/pycompose-ui.xml"
"""Where the accessibility dump is written on the device."""

RECTANGLE = re.compile(r"\[(\d+),(\d+)]\[(\d+),(\d+)]")
"""The accessibility dump's bounds, in pixels."""

QUIET = 200
"""Changed pixels under which two frames of the same area are the same frame."""


class PhoneCheckError(Exception):
    """A step that had to hold, and did not."""


@dataclass(frozen=True)
class Bounds:
    """A node's screen rectangle, in pixels.

    Attributes:
        left: Left edge.
        top: Top edge.
        right: Right edge.
        bottom: Bottom edge.
    """

    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        """Return the point a tap should land on.

        Returns:
            The middle of the rectangle.
        """
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2


@dataclass(frozen=True)
class Node:
    """One node of the accessibility tree.

    Attributes:
        text: Its text, if it has any.
        desc: Its accessibility description, if it has one.
        kind: The last segment of its class name.
        checkable: Whether it is a control that reports a checked state.
        bounds: Its rectangle.
    """

    text: str
    desc: str
    kind: str
    checkable: bool
    bounds: Bounds


def _parse(xml: str) -> list[Node]:
    """Read one accessibility dump.

    Args:
        xml: The dump, as text.

    Returns:
        One node per entry that carries bounds.
    """
    found = []
    for node in ET.fromstring(xml).iter("node"):
        match = RECTANGLE.match(node.get("bounds", ""))
        if match is None:
            continue
        found.append(
            Node(
                text=node.get("text", ""),
                desc=node.get("content-desc", ""),
                kind=node.get("class", "").rsplit(".", 1)[-1],
                checkable=node.get("checkable") == "true",
                bounds=Bounds(*(int(group) for group in match.groups())),
            )
        )
    return found


class Device:
    """One attached device, driven through adb.

    Args:
        serial: The device's serial.
    """

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self._adb = ["adb", "-s", serial]
        self._density: float | None = None

    def adb(self, *args: str, ignore: bool = False) -> bytes:
        """Run one adb subcommand.

        Args:
            *args: The subcommand and its arguments.
            ignore: Return b"" instead of failing when adb exits nonzero.

        Returns:
            Its standard output.

        Raises:
            PhoneCheckError: When it fails and [ignore] is false.
        """
        done = subprocess.run([*self._adb, *args], capture_output=True, check=False)
        if done.returncode != 0 and not ignore:
            reason = done.stderr.decode(errors="replace").strip()
            raise PhoneCheckError(f"adb {' '.join(args)}: {reason}")
        return done.stdout

    def shell(self, *args: str) -> str:
        """Run one shell command on the device.

        Args:
            *args: The command and its arguments.

        Returns:
            Its standard output, decoded.
        """
        return self.adb("shell", *args).decode(errors="replace")

    @property
    def density(self) -> float:
        """Return how many pixels one dp is worth here.

        Returns:
            The ratio the device reports, e.g. 2.0 at 320dpi.

        Raises:
            PhoneCheckError: When the device does not say.
        """
        if self._density is None:
            found = re.search(r"(\d+)", self.shell("wm", "density"))
            if found is None:
                raise PhoneCheckError("the device would not say its density")
            self._density = int(found.group(1)) / 160
        return self._density

    def size(self) -> tuple[int, int]:
        """Return the screen's size in pixels.

        Returns:
            The width and height.

        Raises:
            PhoneCheckError: When the device does not say.
        """
        found = re.search(r"(\d+)x(\d+)", self.shell("wm", "size"))
        if found is None:
            raise PhoneCheckError("the device would not say its screen size")
        return int(found.group(1)), int(found.group(2))

    def tap(self, x: int, y: int) -> None:
        """Tap one point.

        Args:
            x: Horizontal position.
            y: Vertical position.
        """
        self.shell("input", "tap", str(x), str(y))

    def drag(self, y_from: int, y_to: int, millis: int) -> None:
        """Drag slowly down the middle of the screen.

        A slow drag, not a fling: the check measures where the content stopped,
        and momentum would decide that instead.

        Args:
            y_from: Where the finger lands.
            y_to: Where it lifts.
            millis: How long the drag takes.
        """
        middle = str(self.size()[0] // 2)
        self.shell(
            "input", "swipe", middle, str(y_from), middle, str(y_to), str(millis)
        )

    def type_text(self, text: str) -> None:
        """Type into the focused field.

        Args:
            text: Plain words; each space is spelled ``%s`` for the input command.
        """
        self.shell("input", "text", text.replace(" ", "%s"))

    def key(self, code: int) -> None:
        """Press one key, by its key code.

        Args:
            code: The Android key code, e.g. 4 for back.
        """
        self.shell("input", "keyevent", str(code))

    def nodes(self) -> list[Node]:
        """Dump the screen's accessibility tree.

        A dump taken while the window is mid-animation says so and writes
        nothing, so a stale file is removed first and the dump is retried: the
        tree a caller measures has to be of one settled moment.

        Returns:
            One node per entry: its text, description, class, state and rectangle.

        Raises:
            PhoneCheckError: When the tree will not dump.
        """
        for _ in range(3):
            self.shell("rm", "-f", DUMP)
            if "dumped to" in self.shell("uiautomator", "dump", DUMP):
                taken = self.adb("exec-out", "cat", DUMP)
                return _parse(taken.decode(errors="replace"))
            time.sleep(0.5)
        raise PhoneCheckError("the accessibility tree would not dump")

    def keyboard_shown(self) -> bool:
        """Report whether an on-screen keyboard is over the app.

        Returns:
            True while the input method is showing.
        """
        return "mInputShown=true" in self.shell("dumpsys", "input_method")

    def find(
        self,
        *,
        text: str | None = None,
        desc: str | None = None,
        checkable: bool = False,
        nodes: list[Node] | None = None,
    ) -> Bounds | None:
        """Find the first node matching a selector.

        Args:
            text: The node's text, exactly.
            desc: The node's accessibility description, exactly.
            checkable: Whether to take a checkable control instead.
            nodes: A dump to search, or None to take a fresh one.

        Returns:
            Its rectangle, or None when nothing matches.
        """
        for node in self.nodes() if nodes is None else nodes:
            if (
                (checkable and node.checkable)
                or (text is not None and node.text == text)
                or (desc is not None and node.desc == desc)
            ):
                return node.bounds
        return None

    def wait_for(self, text: str, timeout: float = 60.0) -> Bounds:
        """Wait until a text is on screen.

        Args:
            text: The text to wait for.
            timeout: How long to wait, in seconds.

        Returns:
            The text's rectangle.

        Raises:
            PhoneCheckError: When it never appears.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = self.find(text=text)
            if found is not None:
                return found
            time.sleep(0.5)
        raise PhoneCheckError(f"{text!r} never appeared")

    def shot(self) -> Image.Image:
        """Screenshot the device.

        Returns:
            The screen as a grayscale image.
        """
        taken = self.adb("exec-out", "screencap", "-p")
        return Image.open(io.BytesIO(taken)).convert("L")

    def clear_log(self) -> None:
        """Forget every log line so far."""
        self.adb("logcat", "-c")

    def passes(self) -> int:
        """Count the Python passes logged since the log was last cleared.

        Returns:
            The number of pass lines.
        """
        lines = self.adb("logcat", "-d", "-s", PASS_TAG).decode(errors="replace")
        return sum(1 for line in lines.splitlines() if PASS_TAG in line)


def changed(left: Image.Image, right: Image.Image) -> int:
    """Count the pixels two frames disagree on.

    Args:
        left: One frame.
        right: The other.

    Returns:
        The number of pixels differing by more than a rounding step.
    """
    difference = ImageChops.difference(left, right)
    return sum(1 for value in difference.getdata() if value > 8)


def frames_until_settled(
    device: Device,
    area: tuple[int, int, int, int],
    limit: int = 12,
) -> list[Image.Image]:
    """Capture a region until two frames in a row agree.

    Args:
        device: The device to capture from.
        area: The region to keep, as ``(left, top, right, bottom)``.
        limit: How many frames to capture at most.

    Returns:
        The frames, oldest first, ending with the settled one.
    """
    seen: list[Image.Image] = []
    for _ in range(limit):
        frame = device.shot().crop(area)
        if seen and changed(seen[-1], frame) < QUIET:
            break
        seen.append(frame)
    return seen


def serial_or_only_one() -> str:
    """Return the serial of the only device attached.

    Returns:
        The serial.

    Raises:
        PhoneCheckError: When the count of attached devices is not one.
    """
    listed = subprocess.run(["adb", "devices"], capture_output=True, check=True).stdout
    ready = []
    for line in listed.decode(errors="replace").splitlines()[1:]:
        parts = line.split()
        if parts[1:2] == ["device"]:
            ready.append(parts[0])
    if len(ready) != 1:
        raise PhoneCheckError(f"expected one attached device, found {ready}")
    return ready[0]
