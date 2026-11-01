"""Sections the runtime carries and never reads: values, converters, holders.

Each is a flat map of named objects. The codegen reads them off the lock; the
runtime only round-trips them, so the catalog the tests compare is the catalog
that shipped. Adding one is a name in :data:`CARRIED`, not a new field, a new
parse and a new render in three places.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from pycompose.errors import ComponentRegistryError

__all__ = ["CARRIED", "Sections", "parse_sections", "render_sections"]

Sections = Mapping[str, Mapping[str, Mapping[str, object]]]
"""Each carried section's entries, by section name and then by entry name."""

CARRIED = ("valueTypes", "converters", "holders")
"""Every section the runtime carries but does not interpret."""


def parse_sections(
    data: Mapping[str, object],
) -> dict[str, Mapping[str, Mapping[str, object]]]:
    """Read every carried section, refusing one that is not a map of maps.

    Args:
        data: The parsed registry JSON.

    Returns:
        Each present section's entries, by section name; absent sections are
        simply missing.

    Raises:
        ComponentRegistryError: If a present section or one of its entries is
            not an object.
    """
    sections: dict[str, Mapping[str, Mapping[str, object]]] = {}
    for section in CARRIED:
        value = data.get(section)
        if value is None:
            continue
        if not isinstance(value, Mapping):
            raise ComponentRegistryError(f"{section!r} must be an object")
        entries: dict[str, Mapping[str, object]] = {}
        for name, spec in value.items():
            if not isinstance(spec, Mapping):
                raise ComponentRegistryError(f"{section}.{name} must be an object")
            entries[str(name)] = dict(spec)
        sections[section] = MappingProxyType(entries)
    return sections


def render_sections(result: dict[str, object], sections: Sections) -> None:
    """Write each nonempty carried section back in its wire form.

    Args:
        result: The lock-shaped dict being rendered, extended in place.
        sections: The carried sections, as :func:`parse_sections` read them.
    """
    for section in CARRIED:
        entries = sections.get(section)
        if entries:
            result[section] = {name: dict(spec) for name, spec in entries.items()}
