"""Immutable ordered modifier nodes validated through the generated registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from pycompose.core.props import JsonValue
from pycompose.errors import IrValidationError
from pycompose.ir.validator import validate_modifier
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json, thaw_json


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

    def padding(self, value: int | float) -> Modifier:
        """Append nonnegative, uniform dp padding.

        Args:
            value: Padding in dp.

        Returns:
            A new modifier, leaving this one unchanged.
        """
        return self._append("padding", value=value)

    def fill_max_width(self, fraction: int | float = 1) -> Modifier:
        """Append fillMaxWidth with an inclusive zero-to-one fraction.

        Args:
            fraction: Fraction of available width.

        Returns:
            A new modifier.
        """
        return self._append("fillMaxWidth", fraction=fraction)

    def size(self, width: int | float, height: int | float | None = None) -> Modifier:
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

    def clip(self, shape: str) -> Modifier:
        """Append a registry-declared clipping shape.

        Args:
            shape: rectangle, circle or rounded.

        Returns:
            A new modifier.
        """
        return self._append("clip", shape=shape)

    def clickable(self, on_click: str, *, enabled: bool = True) -> Modifier:
        """Append a registered action reference, never a Python callback.

        Args:
            on_click: Registered action id.
            enabled: Whether clicks are enabled.

        Returns:
            A new modifier.
        """
        return self._append("clickable", onClick=on_click, enabled=enabled)

    def to_wire(self) -> dict[str, JsonValue]:
        """Return a detached modifier wire object.

        Returns:
            JSON-ready operations in construction order.
        """
        return cast(dict[str, JsonValue], thaw_json(self.values))
