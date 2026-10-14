"""The palette this app paints with.

The device's appearance is a fact Python cannot observe on its own, so the host
reports it through ``onConfigChanged`` and the declared state carries the answer.
Colours are plain hex because that is what the IR carries; a Material 3 role name
would not survive the crossing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Theme:
    """The colours one appearance paints with.

    Attributes:
        background: Screen background.
        on_surface: Primary text.
        muted: Secondary text.
        primary: Accent for the screen's main command.
        danger: Destructive commands.
    """

    background: str
    on_surface: str
    muted: str
    primary: str
    danger: str

    @classmethod
    def of(cls, state: object) -> Theme:
        """Return the palette matching a declared state's appearance.

        Args:
            state: Any object carrying a ``dark`` flag.

        Returns:
            The matching theme.
        """
        return DARK if getattr(state, "dark", False) else LIGHT


LIGHT = Theme(
    background="#FBF9F7",
    on_surface="#191C1D",
    muted="#6C7779",
    primary="#00696E",
    danger="#B3261E",
)

DARK = Theme(
    background="#101416",
    on_surface="#E2E3E3",
    muted="#98A4A6",
    primary="#4FD8E0",
    danger="#FFB4AB",
)
