"""Immutable ordered modifier nodes validated through the generated registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

from pycompose.core.props import JsonValue
from pycompose.errors import IrValidationError
from pycompose.ir.validator import validate_modifier
from pycompose.state.app_action import AppAction
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json, thaw_json
from pycompose.values import Dp, PaddingValues

_PADDING_SIDES = ("start", "top", "end", "bottom")


@dataclass(frozen=True, slots=True)
class Modifier:
    """An immutable sequence: order and repeated operations affect layout.

    Attributes:
        values: Frozen modifier wire object with ordered operations.
    """

    values: Mapping[str, JsonValue | FrozenJsonValue] = field(
        default_factory=lambda: {"operations": []}
    )

    def __post_init__(self) -> None:
        if "operations" not in self.values:
            raise IrValidationError("Modifier requires an operations array")
        frozen = freeze_json(self.values)
        validate_modifier(frozen)
        object.__setattr__(self, "values", frozen)

    def _append(self, name: str, **props: JsonValue) -> Modifier:
        operations = cast(
            tuple[FrozenJsonValue, ...], self.values.get("operations", ())
        )
        operation = freeze_json({"type": name, **props})
        return Modifier({"operations": (*operations, operation)})

    def padding(
        self,
        value: int | float | dict[str, JsonValue] | None = None,
        *,
        top: int | float | None = None,
        start: int | float | None = None,
        end: int | float | None = None,
        bottom: int | float | None = None,
        horizontal: int | float | None = None,
        vertical: int | float | None = None,
    ) -> Modifier:
        """Append nonnegative padding: uniform in dp, or per side.

        A single value pads every side, as it always has. Keywords name sides:
        ``horizontal`` and ``vertical`` each set two, and the four explicit
        sides win over both. When every side ends up equal the uniform form is
        emitted, so ``padding(4, top=4)`` is exactly ``padding(4)``.

        Args:
            value: Padding in dp for every side, or the tagged PaddingValues
                wire object.
            top: Top padding in dp, winning over value and vertical.
            start: Start padding in dp, winning over value and horizontal.
            end: End padding in dp, winning over value and horizontal.
            bottom: Bottom padding in dp, winning over value and vertical.
            horizontal: Start and end padding in dp.
            vertical: Top and bottom padding in dp.

        Returns:
            A new modifier, leaving this one unchanged.

        Raises:
            IrValidationError: If nothing was given to pad with, or the wire
                dict was combined with side keywords.
        """
        keywords = (top, start, end, bottom, horizontal, vertical)
        if isinstance(value, Mapping):
            if any(side is not None for side in keywords):
                raise IrValidationError(
                    "padding takes either a padding dict or side keywords, not both"
                )
            return self._append("padding", value=dict(value))
        if value is None and not any(side is not None for side in keywords):
            raise IrValidationError("padding needs a value or at least one side")
        sides: dict[str, int | float] = {}
        if value is not None:
            sides = {name: value for name in _PADDING_SIDES}
        if horizontal is not None:
            sides["start"] = horizontal
            sides["end"] = horizontal
        if vertical is not None:
            sides["top"] = vertical
            sides["bottom"] = vertical
        for name, amount in (
            ("top", top),
            ("start", start),
            ("end", end),
            ("bottom", bottom),
        ):
            if amount is not None:
                sides[name] = amount
        every = all(name in sides for name in _PADDING_SIDES)
        if every and len(set(sides.values())) == 1:
            return self._append("padding", value=sides["bottom"])
        return self._append(
            "padding",
            value=PaddingValues(**{name: Dp(amount) for name, amount in sides.items()}),
        )

    def fill_max_width(self, fraction: int | float = 1) -> Modifier:
        """Append fillMaxWidth with an inclusive zero-to-one fraction.

        Args:
            fraction: Fraction of available width.

        Returns:
            A new modifier.
        """
        return self._append("fillMaxWidth", fraction=fraction)

    def size(
        self,
        width: int | float | dict[str, JsonValue],
        height: int | float | dict[str, JsonValue] | None = None,
    ) -> Modifier:
        """Append nonnegative dp size; an omitted height makes a square.

        Args:
            width: Width in dp.
            height: Height in dp, or None to use width.

        Returns:
            A new modifier.
        """
        return self._append(
            "size", width=width, height=width if height is None else height
        )

    def clip(self, shape: str | dict[str, JsonValue]) -> Modifier:
        """Append a registry-declared clipping shape.

        Args:
            shape: rectangle, circle or rounded.

        Returns:
            A new modifier.
        """
        return self._append("clip", shape=shape)

    def background(self, brush: dict[str, JsonValue]) -> Modifier:
        """Paint a decoded native brush behind content.

        Args:
            brush: Tagged Compose Brush descriptor.

        Returns:
            A new ordered modifier.
        """
        return self._append("background", brush=brush)

    def window_insets_padding(self, insets: dict[str, JsonValue]) -> Modifier:
        """Apply density-aware native insets.

        Args:
            insets: Tagged WindowInsets descriptor.

        Returns:
            A new ordered modifier.
        """
        return self._append("windowInsetsPadding", insets=insets)

    def clickable(
        self, on_click: str | AppAction[Any], *, enabled: bool = True
    ) -> Modifier:
        """Append an action reference, never a Python callback.

        Args:
            on_click: An app action, a binding of one, or a registered action id.
            enabled: Whether clicks are enabled.

        Returns:
            A new modifier.
        """
        target = on_click.binding() if isinstance(on_click, AppAction) else on_click
        return self._append("clickable", onClick=target, enabled=enabled)

    def to_wire(self) -> dict[str, JsonValue]:
        """Return a detached modifier wire object.

        Returns:
            JSON-ready operations in construction order.
        """
        return cast(dict[str, JsonValue], thaw_json(self.values))
