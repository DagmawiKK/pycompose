"""Implementation families: an interface of value functions, as host programs.

``rememberDatePickerState(selectableDates: SelectableDates)`` takes an object
whose methods the picker calls while it draws: ``isSelectableDate(Long)`` for
each day, ``isSelectableYear(Int)`` for each year. An interface whose every
member is such a function -- scalars in, a scalar out, nothing else -- is a
family whose fields are host functions, one per method. A method with a body
may go unset and keeps it; an abstract one must be given.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pycompose_codegen.derive.classpath_dump import Inventory
from pycompose_codegen.derive.classpath_types import Declaration

SCALARS = {
    "kotlin/Int": ("integer", "Int"),
    "kotlin/Long": ("integer", "Long"),
    "kotlin/Float": ("number", "Float"),
    "kotlin/Double": ("number", "Double"),
    "kotlin/Boolean": ("boolean", "Boolean"),
}
"""Kotlin types a value function takes and returns: program types, native names."""


def _function(declaration: Declaration) -> bool:
    """A member the host can implement with a program."""
    return (
        declaration.document.get("declarationKind") == "function"
        and declaration.document.get("visibility") == "PUBLIC"
        and declaration.document.get("modality") in {"OPEN", "ABSTRACT"}
        and not declaration.document.get("suspend")
        and not declaration.document.get("typeParameters")
        and not declaration.composable
        and declaration.receiver is None
        and not declaration.context_receivers
        and declaration.return_type.classifier in SCALARS
        and not declaration.return_type.nullable
        and all(
            p.type.classifier in SCALARS and not p.type.nullable and not p.has_default
            for p in declaration.parameters
        )
    )


def implementation_members(
    found: Inventory, classifier: str
) -> tuple[Declaration, ...] | None:
    """An interface's methods, when each is a value function and nothing else is.

    Args:
        found: The pinned inventory.
        classifier: The candidate's slash classifier.

    Returns:
        Its methods by name, or None when it is not an implementation family.
    """
    dotted = classifier.replace("/", ".")
    found_class = next((c for c in found.classes if c.classifier == dotted), None)
    if (
        found_class is None
        or found_class.class_kind != "INTERFACE"
        or found_class.visibility != "PUBLIC"
        or set(found_class.supertypes) - {"kotlin/Any"}
    ):
        return None
    members = tuple(
        sorted(
            (
                d
                for d in found.declarations
                if d.dispatch_receiver is not None
                and d.dispatch_receiver.classifier == classifier
            ),
            key=lambda d: d.name,
        )
    )
    names = [d.name for d in members]
    if not members or len(set(names)) != len(names) or not all(map(_function, members)):
        return None
    return members


def implementation_families(
    found: Inventory, classifiers: Iterable[str], known: set[str], since: str
) -> dict[str, dict[str, Any]]:
    """The implementation family of each such interface among ``classifiers``.

    Args:
        found: The pinned inventory.
        classifiers: Parameter types declarations take (slash form).
        known: Kotlin types an approved family already binds (dotted).
        since: The schema version a new family enters at.

    Returns:
        Each family's lock entry, by family name.
    """
    families: dict[str, dict[str, Any]] = {}
    for classifier in sorted(set(classifiers)):
        dotted = classifier.replace("/", ".")
        members = None if dotted in known else implementation_members(found, classifier)
        if members is None:
            continue
        families[dotted.rsplit(".", 1)[-1]] = {
            "family": dotted.rsplit(".", 1)[-1],
            "kind": "implementation",
            "kotlinType": dotted,
            "since": since,
            "source": {"owner": classifier, "members": "public value functions"},
            "parameters": {d.name: _method(d) for d in members},
            "native": {"implements": dotted},
        }
    return families


def _method(declaration: Declaration) -> dict[str, Any]:
    params = [SCALARS[p.type.classifier] for p in declaration.parameters]
    result = SCALARS[declaration.return_type.classifier]
    return {
        "type": "program",
        "signature": {"params": [p[0] for p in params], "result": result[0]},
        "native": {
            "parameters": [
                {"name": p.name, "type": t[1]}
                for p, t in zip(declaration.parameters, params, strict=True)
            ],
            "result": result[1],
        },
        # An unset method with a body keeps it; that body is its default.
        **(
            {"required": True}
            if declaration.document.get("modality") == "ABSTRACT"
            else {}
        ),
    }
