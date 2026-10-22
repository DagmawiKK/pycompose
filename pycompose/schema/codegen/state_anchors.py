"""Closed enum contracts for native anchor projections."""

from typing import Any

from pycompose.schema.codegen.rules import die

SWIPE_VALUES = ("settled", "startToEnd", "endToStart")
SHEET_VALUES = ("hidden", "partiallyExpanded", "expanded")


def validate_anchor(
    where: str, value: object, prop: dict[str, Any], values: tuple[str, ...]
) -> None:
    """Require exactly a family's native anchor aliases and an optional desired value.

    Args:
        where: Prefix for validation failures.
        value: The desired prop's name.
        prop: Its schema entry.
        values: The family's reviewed lowerCamel wire aliases.
    """
    if prop.get("type") != "enum" or prop.get("values") != list(values):
        die(
            f"{where}: prop {value!r} must be an enum with the values "
            + ", ".join(values)
        )
    if prop.get("required"):
        die(f"{where}: prop {value!r} must be optional")
    if "default" in prop:
        die(f"{where}: prop {value!r} must not declare a default")


def validate_optional_field(
    where: str, prop: dict[str, Any], prop_name: str, field: str
) -> None:
    """Require an optional report carrying exactly its one named field.

    Args:
        where: Prefix for validation failures.
        prop: The actionId prop's schema entry.
        prop_name: The prop's name, for the message.
        field: The one payload field the report must carry.
    """
    payload = prop.get("payload")
    names = (
        [entry.get("name") for entry in payload] if isinstance(payload, list) else []
    )
    if prop.get("type") != "actionId" or prop.get("required") or names != [field]:
        die(f"{where}: prop {prop_name!r} must optionally report {field!r}")
