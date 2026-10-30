"""The native calls behind the modifiers policy declares, found in the pin.

Policy states a modifier's wire contract -- ``padding`` takes ``value``, a dp
whose family is ``PaddingValues`` -- and the pin says which ``Modifier``
extension that contract calls. Each prop binds to the parameter of the same
name, or else to the one parameter of its type; every parameter left over must
have a default. Of several overloads that bind, Kotlin calls the one that
leaves the fewest defaults in use, and so does the generated code; a tie is
refused, never guessed.

Two shapes are not a plain call:

* A dp prop whose family is not ``Dp`` also rides the wire as a bare number
  (ADR-0036); the bare form calls the overload taking that one ``Dp``.
* ``semantics`` takes a block on a receiver. Its props bind to the receiver's
  members instead: a settable extension property of the prop's name, or a
  function of no arguments for a flag. An enumerated prop names the companion
  constants of the property's type.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Declaration, Inventory
from pycompose_codegen.derive.propose import identity

MODIFIER = "androidx/compose/ui/Modifier"
DP = "androidx/compose/ui/unit/Dp"
EXTENSION = "kotlin/ExtensionFunctionType"

SCALARS = {
    "number": frozenset({"kotlin/Float", "kotlin/Double"}),
    "integer": frozenset({"kotlin/Int", "kotlin/Long"}),
    "boolean": frozenset({"kotlin/Boolean"}),
    "string": frozenset({"kotlin/String"}),
    "actionId": frozenset({"kotlin/Function0"}),
}
"""The parameter types a scalar prop may fill."""


def _dotted(classifier: str) -> str:
    return classifier.replace("/", ".")


def _pascal(value: str) -> str:
    return value[:1].upper() + value[1:]


def _accepts(spec: dict[str, Any], classifier: str, families: dict[str, Any]) -> bool:
    """Whether a parameter of ``classifier`` can take the prop's value."""
    if "valueType" in spec:
        family = families.get(spec["valueType"])
        return family is not None and _dotted(classifier) == family["kotlinType"]
    return classifier in SCALARS.get(spec["type"], frozenset())


def _bind(
    props: dict[str, Any], declaration: Declaration, families: dict[str, Any]
) -> dict[str, Any] | None:
    """Each prop's parameter, or None when the overload cannot take them all."""
    free = {p.name: p for p in declaration.parameters}
    bound: dict[str, Any] = {}
    for name, spec in props.items():
        same = free.get(name)
        if same is not None and _accepts(spec, same.type.classifier, families):
            parameter = same
        else:
            typed = [
                p for p in free.values() if _accepts(spec, p.type.classifier, families)
            ]
            if len(typed) != 1:
                return None
            parameter = typed[0]
        del free[parameter.name]
        bound[name] = {
            "parameter": parameter.name,
            "type": _dotted(parameter.type.classifier),
        }
    if any(not p.has_default for p in free.values()):
        return None
    return bound


def _defaults_used(declaration: Declaration, binding: dict[str, Any]) -> int:
    """How many parameters the call leaves to their defaults."""
    passed = {argument["parameter"] for argument in binding.values()}
    return sum(p.has_default and p.name not in passed for p in declaration.parameters)


def _bare(name: str, prop: str, candidates: list[Declaration]) -> dict[str, Any]:
    """The overload a bare dp number calls: one required ``Dp`` and nothing else."""
    taking = [
        d
        for d in candidates
        if [p.type.classifier for p in d.parameters if not p.has_default] == [DP]
        and len(d.parameters) == 1
    ]
    if len(taking) != 1:
        raise ValueError(f"{name}.{prop}: no single overload takes a bare Dp")
    return {"parameter": taking[0].parameters[0].name, "source": identity(taking[0])}


def _members(found: Inventory, receiver: str) -> dict[str, Declaration]:
    """The extension members declared on ``receiver``, by name."""
    return {
        d.name: d
        for d in found.declarations
        if d.receiver is not None and d.receiver.classifier == receiver
    }


def _constants(found: Inventory, owner: str) -> frozenset[str]:
    """The companion constants ``owner`` declares."""
    companion = f"{_dotted(owner)}$Companion"
    return frozenset(d.name for d in found.declarations if d.owner == companion)


def _block(
    name: str,
    props: dict[str, Any],
    declaration: Declaration,
    found: Inventory,
) -> dict[str, Any] | None:
    """The receiver-block form of a call, or None when the overload has none."""
    blocks = [
        p
        for p in declaration.parameters
        if not p.has_default and EXTENSION in p.type.annotations
    ]
    rest = [p for p in declaration.parameters if p not in blocks]
    if len(blocks) != 1 or any(not p.has_default for p in rest):
        return None
    receiver = blocks[0].type.arguments[0][1]
    if receiver is None:
        return None
    members = _members(found, receiver.classifier)
    arguments: dict[str, Any] = {}
    for prop, spec in props.items():
        member = members.get(prop)
        if member is None:
            raise ValueError(f"{name}.{prop}: the receiver declares no {prop!r}")
        kind = member.document.get("declarationKind")
        if kind == "function" and spec["type"] == "boolean" and not member.parameters:
            arguments[prop] = {"member": "function", "source": identity(member)}
            continue
        setter = (member.document.get("accessors") or {}).get("setter")
        if kind != "property" or setter is None:
            raise ValueError(f"{name}.{prop}: {prop!r} is not a settable property")
        classifier = member.return_type.classifier
        entry: dict[str, Any] = {
            "member": "property",
            "type": _dotted(classifier),
            "source": identity(member),
        }
        if spec["type"] == "enum":
            declared = _constants(found, classifier)
            wanted = {value: _pascal(value) for value in spec["values"]}
            missing = sorted(v for v, c in wanted.items() if c not in declared)
            if missing:
                raise ValueError(f"{name}.{prop}: no constant for {missing}")
            entry["constants"] = wanted
        elif classifier not in SCALARS.get(spec["type"], frozenset()):
            raise ValueError(f"{name}.{prop}: {prop!r} takes {_dotted(classifier)}")
        arguments[prop] = entry
    return {
        "function": f"{declaration.package}.{declaration.name}",
        "source": identity(declaration),
        "block": {
            "parameter": blocks[0].name,
            "receiver": _dotted(receiver.classifier),
        },
        "arguments": arguments,
    }


def _call(
    name: str, props: dict[str, Any], found: Inventory, families: dict[str, Any]
) -> dict[str, Any]:
    """The call one policy modifier makes."""
    candidates = [
        d
        for d in found.declarations
        if d.name == name
        and d.receiver is not None
        and d.receiver.classifier == MODIFIER
        and d.dispatch_receiver is None
    ]
    bound = [
        (_defaults_used(d, binding), d, binding)
        for d in candidates
        if (binding := _bind(props, d, families)) is not None
    ]
    if not bound:
        for declaration in candidates:
            block = _block(name, props, declaration, found)
            if block is not None:
                return block
        raise ValueError(f"{name}: no overload in the pin takes these props")
    fewest = min(unused for unused, _, _ in bound)
    chosen = [(d, b) for unused, d, b in bound if unused == fewest]
    if len(chosen) > 1:
        raise ValueError(f"{name}: several overloads take these props equally")
    declaration, binding = chosen[0]
    call: dict[str, Any] = {
        "function": f"{declaration.package}.{declaration.name}",
        "source": identity(declaration),
        "arguments": binding,
    }
    bare = {
        prop: _bare(name, prop, candidates)
        for prop, spec in props.items()
        if spec["type"] == "dp" and spec.get("valueType") not in (None, "Dp")
    }
    if bare:
        call["bare"] = bare
    return call


def core_modifiers(
    found: Inventory,
    modifiers: dict[str, dict[str, Any]],
    families: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Find the native call every policy modifier makes.

    Args:
        found: The pinned inventory.
        modifiers: The modifiers policy declares, by wire name.
        families: Approved value families, by family name.

    Returns:
        Each modifier with its ``call`` added, and each one that does not
        derive with why.
    """
    derived: dict[str, dict[str, Any]] = {}
    refused: dict[str, str] = {}
    for name, entry in sorted(modifiers.items()):
        try:
            derived[name] = {
                **entry,
                "call": _call(name, entry["props"], found, families),
            }
        except ValueError as exc:
            refused[name] = str(exc)
    return derived, refused
