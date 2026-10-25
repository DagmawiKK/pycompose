"""Overloads behind one Python name, told apart by keywords (plan 31 §12.5).

A native composable often has several overloads -- a plain and a clickable
``Card``, an indeterminate and a determinate progress indicator. Each is its
own catalog entry and wire type; an entry with ``overloadOf`` is reached
through its primary's Python name, and the keywords a call passes choose it.

Keywords choose soundly only if no call is valid for two overloads. That is
proven here, per name, from each entry's required and accepted keywords; the
compiler gives an overload that fails it a name of its own instead.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, NoReturn

CONTENT = "content"
"""The keyword children arrive under, positionally or by name."""


def python_name(prop: str) -> str:
    """Spell a wire prop as its Python keyword.

    Args:
        prop: The wire prop name.

    Returns:
        The snake_case keyword.
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "_", prop).lower()


def keywords(entry: dict[str, Any]) -> tuple[frozenset[str], frozenset[str]]:
    """The keywords a call must pass, and every keyword it may pass.

    ``id`` and ``modifier`` are common to every component and say nothing
    about which overload a call means, so neither set holds them.

    Args:
        entry: A catalog component entry.

    Returns:
        Required keywords, then accepted keywords.
    """
    props = {
        name: spec
        for name, spec in entry["props"].items()
        if name != "modifier" and "protocol" not in spec
    }
    accepted = {python_name(name) for name in props}
    accepted |= {python_name(slot) for slot in entry.get("slots", {})}
    if entry["children"].get("allowed"):
        accepted.add(CONTENT)
    required = {
        python_name(name) for name, spec in props.items() if spec.get("required")
    }
    return frozenset(required), frozenset(accepted)


def ambiguous(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Whether some call is valid for both entries.

    A call is valid for an entry when it passes every required keyword and no
    keyword the entry does not accept; one call satisfies both exactly when
    the union of their required keywords is accepted by both.

    Args:
        first: One entry.
        second: Another entry.

    Returns:
        True when keywords cannot always tell them apart.
    """
    required_first, accepted_first = keywords(first)
    required_second, accepted_second = keywords(second)
    return required_first | required_second <= accepted_first & accepted_second


def groups(components: dict[str, Any]) -> dict[str, list[str]]:
    """Each primary's overloads, in name order.

    Args:
        components: The catalog's components.

    Returns:
        Overload names keyed by the primary they are reached through.
    """
    found: dict[str, list[str]] = {}
    for name, entry in sorted(components.items()):
        primary = entry.get("overloadOf")
        if primary is not None:
            found.setdefault(primary, []).append(name)
    return found


def validate(components: dict[str, Any], die: Callable[[str], NoReturn]) -> None:
    """Refuse an overload group keywords cannot dispatch.

    Args:
        components: The catalog's components.
        die: The validator's failure function; it does not return.
    """
    for primary, overloads in groups(components).items():
        entry = components.get(primary)
        if entry is None or "overloadOf" in entry:
            die(f"component {overloads[0]!r}: overloadOf names no primary {primary!r}")
        members = [primary, *overloads]
        for index, first in enumerate(members):
            for second in members[index + 1 :]:
                if ambiguous(components[first], components[second]):
                    die(f"keywords cannot tell {first!r} from {second!r}")
