"""Immutable ordered modifier nodes validated through the generated registry.

Every operation is generated from the catalog (:mod:`.generated_modifiers`);
what is written here is the chain itself and the two conveniences a person
designed: padding by side and a square size.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from pycompose.contract.catalog import REGISTRY
from pycompose.core.props import JsonValue
from pycompose.core.values import named_value
from pycompose.errors import IrValidationError
from pycompose.ui._rules import validate_modifier
from pycompose.ui.generated_modifiers import GeneratedOperations
from pycompose.ui.modifier_operation import _Operation
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json, thaw_json
from pycompose.values import Dp, PaddingValues

_PADDING_SIDES = ("start", "top", "end", "bottom")


@dataclass(frozen=True, slots=True)
class Modifier(GeneratedOperations):
    """An immutable sequence: order and repeated operations affect layout.

    Every operation comes from :class:`GeneratedOperations`, generated from the
    catalog; ``padding`` and ``size`` add their conveniences over it.

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

    # A slotted dataclass is a new class, so the conveniences below name it in
    # super(): the zero-argument form would still see the class before slots.

    def _append(self, name: str, **props: JsonValue) -> Modifier:
        operations = cast(
            tuple[FrozenJsonValue, ...], self.values.get("operations", ())
        )
        rules = REGISTRY.modifiers.get(name, {})
        for key, value in props.items():
            rule = rules.get(key)
            if rule is not None and rule.type == "enum" and rule.value_type:
                props[key] = cast(
                    "JsonValue",
                    named_value(rule.value_type, value, REGISTRY.value_types),
                )
        operation = freeze_json({"type": name, **props})
        return Modifier({"operations": (*operations, operation)})

    @_Operation
    def padding(
        self,
        value: JsonValue = None,
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
            return super(Modifier, self).padding(dict(value))
        if value is None and not any(side is not None for side in keywords):
            raise IrValidationError("padding needs a value or at least one side")
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int | float)
        ):
            raise IrValidationError("padding takes dp, a padding dict or sides")
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
            return super(Modifier, self).padding(sides["bottom"])
        return super(Modifier, self).padding(
            PaddingValues(**{name: Dp(amount) for name, amount in sides.items()})
        )

    @_Operation
    def size(
        self,
        width: JsonValue,
        height: JsonValue = None,
    ) -> Modifier:
        """Append nonnegative dp size; an omitted height makes a square.

        Args:
            width: Width in dp.
            height: Height in dp, or None to use width.

        Returns:
            A new modifier.
        """
        return super(Modifier, self).size(width, width if height is None else height)

    def to_wire(self) -> dict[str, JsonValue]:
        """Return a detached modifier wire object.

        Returns:
            JSON-ready operations in construction order.
        """
        return cast(dict[str, JsonValue], thaw_json(self.values))
