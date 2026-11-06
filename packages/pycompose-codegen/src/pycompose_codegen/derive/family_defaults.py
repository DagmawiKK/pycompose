"""One family parameter's wire rule and the default it falls back on.

A default is the compiler's evidence when the vocabulary can spell it. When it
cannot -- an internal token -- and the call can be made with no arguments, the
result exposes the value under the parameter's name, so the default is read
back from there (``lightColorScheme().primary``).
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Declaration, Inventory, Parameter
from pycompose_codegen.derive.propose_lookup import _rule


def parameter_rule(
    parameter: Parameter,
    families: dict[str, str],
    defaults: dict[str, Any] | None,
    base: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """One bound parameter's wire rule, with its compiler-resolved default.

    A default the vocabulary cannot render (``lightColorScheme``'s internal
    palette tokens) is read back from the call made with no arguments, where
    the result exposes it under the parameter's name.
    """
    if parameter.vararg_type:
        raise ValueError(f"{parameter.name}: varargs need a collection policy")
    rule = _rule(parameter.type, families)
    if not parameter.has_default:
        rule["required"] = True
        return rule
    expression = (defaults or {}).get(parameter.name)
    if expression is None or expression.get("kind") == "unsupported":
        if parameter.name in base:
            expression = {"kind": "base"}
        elif expression is None:
            raise ValueError(f"{parameter.name}: missing compiler-resolved default")
        else:
            raise ValueError(f"{parameter.name}: {expression['reason']}")
    rule["default"] = expression
    return rule


def readable(found: Inventory, source: Declaration) -> frozenset[str]:
    """Parameters the call with no arguments exposes back, by name and type.

    Only a call every parameter of which is defaulted has such a base.
    """
    if not all(p.has_default for p in source.parameters):
        return frozenset()
    result = source.return_type.classifier.replace("/", ".")
    exposed = {
        (d.name, d.return_type.classifier)
        for d in found.declarations
        if d.owner == result
        and d.document.get("declarationKind") == "property"
        and d.document.get("visibility") == "PUBLIC"
        and not d.return_type.nullable
    }
    return frozenset(
        p.name for p in source.parameters if (p.name, p.type.classifier) in exposed
    )
