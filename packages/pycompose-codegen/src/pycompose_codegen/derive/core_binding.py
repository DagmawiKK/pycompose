"""One policy prop to one pin parameter, and the overload taking them all.

Policy states a modifier's wire contract -- ``padding`` takes ``value``, a dp
whose family is ``PaddingValues`` -- and the pin says which ``Modifier``
extension that contract calls. Each prop binds to the parameter of the same
name, or else to the one parameter of its type; every parameter left over must
have a default. Of several overloads that bind, Kotlin calls the one that
leaves the fewest defaults in use, and so does the generated code; a tie is
refused, never guessed.

A dp prop whose family is not ``Dp`` also rides the wire as a bare number
(ADR-0036); the bare form calls the overload taking that one ``Dp``.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Declaration, Inventory
from pycompose_codegen.derive.propose import identity

MODIFIER = "androidx/compose/ui/Modifier"
DP = "androidx/compose/ui/unit/Dp"
MATERIAL_2 = "androidx.compose.material."
"""Material 2's package; Material 3's is ``androidx.compose.material3``."""

SCALARS = {
    "number": frozenset({"kotlin/Float", "kotlin/Double"}),
    "integer": frozenset({"kotlin/Int", "kotlin/Long"}),
    "boolean": frozenset({"kotlin/Boolean"}),
    "string": frozenset({"kotlin/String"}),
    "actionId": frozenset({"kotlin/Function0"}),
}
"""The parameter types a scalar prop may fill."""


def dotted(classifier: str) -> str:
    """A slash-separated classifier as the pin spells it elsewhere."""
    return classifier.replace("/", ".")


def pascal(value: str) -> str:
    """An enumerated wire value as the companion constant naming it."""
    return value[:1].upper() + value[1:]


def accepts(spec: dict[str, Any], classifier: str, families: dict[str, Any]) -> bool:
    """Whether a parameter of ``classifier`` can take the prop's value."""
    if "valueType" in spec:
        family = families.get(spec["valueType"])
        return family is not None and dotted(classifier) == family["kotlinType"]
    if spec["type"] == "dp":
        # A bare dp number (ADR-0036) fills a Dp parameter.
        return classifier == DP
    return classifier in SCALARS.get(spec["type"], frozenset())


def candidates(found: Inventory, name: str) -> list[Declaration]:
    """The pin's public ``Modifier`` extensions of one name, Material 2 aside."""
    return [
        d
        for d in found.declarations
        if d.name == name
        and d.receiver is not None
        and d.receiver.classifier == MODIFIER
        and d.dispatch_receiver is None
        and d.document.get("visibility") == "PUBLIC"
        and not f"{d.package}.".startswith(MATERIAL_2)
    ]


def bind(
    props: dict[str, Any], declaration: Declaration, families: dict[str, Any]
) -> dict[str, Any] | None:
    """Each prop's parameter, or None when the overload cannot take them all."""
    free = {p.name: p for p in declaration.parameters}
    bound: dict[str, Any] = {}
    for name, spec in props.items():
        same = free.get(name)
        if same is not None and accepts(spec, same.type.classifier, families):
            parameter = same
        else:
            typed = [
                p for p in free.values() if accepts(spec, p.type.classifier, families)
            ]
            if len(typed) != 1:
                return None
            parameter = typed[0]
        del free[parameter.name]
        bound[name] = {
            "parameter": parameter.name,
            "type": dotted(parameter.type.classifier),
        }
    if any(not p.has_default for p in free.values()):
        return None
    return bound


def defaults_used(declaration: Declaration, binding: dict[str, Any]) -> int:
    """How many parameters the call leaves to their defaults."""
    passed = {argument["parameter"] for argument in binding.values()}
    return sum(p.has_default and p.name not in passed for p in declaration.parameters)


def bare(name: str, prop: str, overloads: list[Declaration]) -> dict[str, Any]:
    """The overload a bare dp number calls: one required ``Dp`` and nothing else."""
    taking = [
        d
        for d in overloads
        if [p.type.classifier for p in d.parameters if not p.has_default] == [DP]
        and len(d.parameters) == 1
    ]
    if len(taking) != 1:
        raise ValueError(f"{name}.{prop}: no single overload takes a bare Dp")
    return {"parameter": taking[0].parameters[0].name, "source": identity(taking[0])}
