"""Constant families the pin implies: enumerations a parameter may name.

``menuAnchor(type: ExposedDropdownMenuAnchorType)`` takes one of the values
``ExposedDropdownMenuAnchorType`` lists on its companion. A Kotlin value class
or enum whose values are its own public constants is an enumeration, and
crosses the wire by name, as the approved ``TextAlign`` family does. Only those
shapes qualify: ``FocusRequester.Default`` and ``KeyboardOptions.Default`` are
constants too, but of handles and configurations, not of an enumeration.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory
from pycompose_codegen.derive.propose_families import propose_members

VALUE_CLASS = "kotlin/jvm/JvmInline"


def constant_families(
    found: Inventory, classifiers: Iterable[str], known: set[str], since: str
) -> dict[str, dict[str, Any]]:
    """The constant family of each enumeration among ``classifiers``.

    Args:
        found: The pinned inventory.
        classifiers: Parameter types planned declarations take (slash form).
        known: Kotlin types an approved family already binds (dotted).
        since: The schema version a new family enters at.

    Returns:
        Each derived family's lock entry, by family name.
    """
    classes = {c.classifier: c for c in found.classes}
    families: dict[str, dict[str, Any]] = {}
    for classifier in sorted(set(classifiers)):
        dotted = classifier.replace("/", ".")
        found_class = classes.get(dotted)
        if dotted in known or found_class is None:
            continue
        enum = found_class.class_kind == "ENUM_CLASS"
        value = VALUE_CLASS in (found_class.document.get("annotations") or {})
        if not (enum or value):
            continue
        name = dotted.rsplit(".", 1)[-1]
        try:
            family = propose_members(
                found,
                classifier if enum else f"{classifier}$Companion",
                {"family": name, "kotlinType": dotted},
                since=since,
            )
        except ValueError:
            continue
        # One named value is a default, not a choice between values.
        if len(family["parameters"]["name"]["values"]) >= 2:
            families[name] = family
    return families
