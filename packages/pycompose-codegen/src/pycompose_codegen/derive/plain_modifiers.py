"""Plain ``Modifier`` extensions, derived from the pin.

``Modifier.alpha``, ``Modifier.border`` and ``Modifier.zIndex`` are top-level
extensions any node may wear. Each public one becomes a wire operation whose
props bind exactly as a component's do; the native call it makes is then found
as a policy modifier's is (:mod:`.core_modifiers`). A modifier policy already
states keeps policy's wire contract.

Some are left out by rule, each with its reason in the report: Material 2's,
since the catalog draws Material 3; tooling-only ones; and a name several
overloads take with props, until the host chooses among them by the props
present.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pycompose_codegen.derive.classpath_dump import Declaration, Inventory
from pycompose_codegen.derive.core_modifiers import MATERIAL_2, MODIFIER
from pycompose_codegen.derive.scoped_modifiers import _parameters, modifier_props


def plain_declarations(found: Inventory) -> list[Declaration]:
    """Every public, current ``Modifier`` extension declared outside a scope.

    Args:
        found: The pinned inventory.

    Returns:
        The declarations, in a stable order.
    """
    return sorted(
        (
            d
            for d in found.declarations
            if d.receiver is not None
            and d.receiver.classifier == MODIFIER
            and d.dispatch_receiver is None
            and d.document.get("declarationKind") == "function"
            and d.document.get("visibility") == "PUBLIC"
            and "kotlin/Deprecated" not in d.annotations
            and d.return_type.classifier == MODIFIER
        ),
        key=lambda d: (d.name, d.jvm_descriptor or ""),
    )


def _left_out(declaration: Declaration) -> str | None:
    """Why a modifier is not exposed by rule, or None when it is."""
    if f"{declaration.package}.".startswith(MATERIAL_2):
        return "a Material 2 modifier; the catalog draws Material 3"
    if declaration.name.startswith("tooling"):
        return "a tooling aid; it changes nothing an app ships"
    return None


def plain_modifiers(
    found: Inventory,
    families: dict[str, str],
    family_specs: dict[str, dict[str, Any]],
    defaults: dict[tuple[str, str, str], dict[str, Any]],
    taken: frozenset[str],
    since: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Derive each plain modifier whose one bindable overload takes wire props.

    Args:
        found: The pinned inventory.
        families: Approved value families, by the classifier they bind.
        family_specs: The same families' specs, by family name.
        defaults: Compiler-resolved defaults by JVM identity.
        taken: Modifier names policy or a scope already uses.
        since: The schema version a new operation enters at.

    Returns:
        The lock entries by wire name, and each refused name's reason.
    """
    bindable: dict[str, list[dict[str, Any]]] = defaultdict(list)
    refused: dict[str, str] = {}
    for declaration in plain_declarations(found):
        name = declaration.name
        if name in taken:
            continue
        reason = _left_out(declaration)
        if reason is not None:
            refused.setdefault(name, reason)
            continue
        own = defaults.get(
            (
                declaration.owner,
                declaration.jvm_name or "",
                declaration.jvm_descriptor or "",
            ),
            {},
        )
        try:
            props, renamed = modifier_props(
                name, _parameters(declaration, families, own), family_specs
            )
        except ValueError as exc:
            refused.setdefault(name, str(exc))
            continue
        if renamed:
            refused.setdefault(name, "a parameter is named like the operation's tag")
            continue
        bindable[name].append(props)
    derived: dict[str, dict[str, Any]] = {}
    for name, forms in sorted(bindable.items()):
        refused.pop(name, None)
        if len(forms) > 1:
            refused[name] = (
                "several overloads take wire props; the host does not yet choose "
                "among them by the props present"
            )
            continue
        derived[name] = {"since": since, "props": forms[0]}
    return derived, refused
