"""Typed one-shot requests for the host: at-most-once, never replayed.

An effect may be lost if the process dies before the host runs it, so anything
that must happen belongs in state instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from pycompose.core.effect import Effect

__all__ = [
    "Finish",
    "Haptic",
    "Navigate",
    "OpenUrl",
    "PickFile",
    "Toast",
    "TypedEffect",
]


class TypedEffect:
    """A typed effect: its kind, and its fields as the effect's payload.

    Attributes:
        kind: The registered effect kind.
    """

    kind: ClassVar[str]

    def effect(self) -> Effect:
        """Return the effect the host runs.

        Returns:
            The registered effect kind with this effect's fields.
        """
        payload = dict(vars(self))
        return Effect(self.kind, payload)


@dataclass(frozen=True)
class Toast(TypedEffect):
    """Show a short message.

    Attributes:
        kind: The registered effect kind.
        message: The text to show.
    """

    kind: ClassVar[str] = "toast"
    message: str


@dataclass(frozen=True)
class Haptic(TypedEffect):
    """Play the platform's tap feedback.

    Attributes:
        kind: The registered effect kind.
    """

    kind: ClassVar[str] = "haptic"


@dataclass(frozen=True)
class OpenUrl(TypedEffect):
    """Open a URL in the app the system chooses.

    Attributes:
        kind: The registered effect kind.
        url: The address to open.
    """

    kind: ClassVar[str] = "openUrl"
    url: str


@dataclass(frozen=True)
class PickFile(TypedEffect):
    """Let the user pick a file with the system picker.

    The host copies the pick into the app's media cache and answers with
    :meth:`ViewModel.on_file_picked`; the bytes never cross the bridge.

    Attributes:
        kind: The registered effect kind.
        request: Handed back with the answer, to tell picks apart.
        accept: A MIME type such as ``image/*``, which opens the photo picker,
            or ``*/*`` for any file.
    """

    kind: ClassVar[str] = "pickFile"
    request: str
    accept: str = "*/*"


@dataclass(frozen=True)
class Navigate(TypedEffect):
    """Ask the host to show another route.

    Attributes:
        kind: The registered effect kind.
        route: The route to show.
    """

    kind: ClassVar[str] = "navigate"
    route: str


@dataclass(frozen=True)
class Finish(TypedEffect):
    """Close the screen the app runs in.

    Attributes:
        kind: The registered effect kind.
    """

    kind: ClassVar[str] = "finish"
