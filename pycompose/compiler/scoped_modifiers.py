"""Modifiers a composition scope declares, derived from the pin.

``RowScope.weight``, ``BoxScope.align`` and ``ExposedDropdownMenuBoxScope.menuAnchor``
are ``Modifier`` extensions that are members of a scope: only a child composed
inside that scope can wear them, and the menu's anchor is one. Each becomes a
wire modifier whose props bind exactly as a component's do; the host applies
it on the receiver the child's parent lambda carries (ADR-0055), and reports
one worn outside its scope.

A name several scopes declare with the same props (``weight`` on rows and
columns) is one operation; one whose props differ by scope (``align`` takes a
vertical, horizontal or two-way alignment) is one operation per scope, named
after it: ``rowAlign``, ``columnAlign``, ``boxAlign``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from pycompose.compiler.candidate_props import wire_prop
from pycompose.compiler.classpath_dump import Declaration, Inventory
from pycompose.compiler.components import bind_parameter
from pycompose.compiler.opt_ins import opt_in_index, required_opt_ins
from pycompose.compiler.propose import identity
from pycompose.compiler.slots import slot_scopes

MODIFIER = "androidx/compose/ui/Modifier"
DISCRIMINATOR = "type"
"""The key a wire modifier operation names itself by."""


def scoped_declarations(found: Inventory) -> list[Declaration]:
    """Every public ``Modifier`` member a scope a host holds declares.

    Args:
        found: The pinned inventory.

    Returns:
        The declarations, in a stable order.
    """
    scopes = slot_scopes(found.declarations)
    return sorted(
        (
            d
            for d in found.declarations
            if d.receiver is not None
            and d.receiver.classifier == MODIFIER
            and d.dispatch_receiver is not None
            and d.dispatch_receiver.classifier in scopes
            and d.document.get("visibility") == "PUBLIC"
            and "kotlin/Deprecated" not in d.annotations
            and d.return_type.classifier == MODIFIER
        ),
        key=lambda d: (d.name, _scope(d), d.jvm_descriptor or ""),
    )


def scoped_modifiers(
    found: Inventory,
    families: dict[str, str],
    family_specs: dict[str, dict[str, Any]],
    defaults: dict[tuple[str, str, str], dict[str, Any]],
    taken: frozenset[str],
    since: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Derive the scope-declared modifiers every parameter of which binds.

    Args:
        found: The pinned inventory.
        families: Approved value families, by the classifier they bind.
        family_specs: The same families' specs, by family name.
        defaults: Compiler-resolved defaults by JVM identity.
        taken: Modifier names approved policy already uses.
        since: The schema version a new operation enters at: older snapshots
            cannot carry it.

    Returns:
        The lock entries by wire name, and each refused declaration's reason.
    """
    index = opt_in_index(found)
    planned: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    refused: dict[str, str] = {}
    declarations = scoped_declarations(found)
    # The generated call passes the bound arguments alone, so a name a scope
    # declares more than once could resolve to either: refused, not guessed.
    overloads: dict[tuple[str, str], int] = defaultdict(int)
    for declaration in declarations:
        overloads[(_scope(declaration), declaration.name)] += 1
    for declaration in declarations:
        scope = _scope(declaration)
        label = f"{scope.replace('/', '.')}.{declaration.name}"
        if overloads[(scope, declaration.name)] > 1:
            refused[label] = "the scope declares several overloads of it"
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
                label, _parameters(declaration, families, own), family_specs
            )
        except ValueError as exc:
            refused[label] = str(exc)
            continue
        scoped: dict[str, Any] = {
            "scope": scope.replace("/", "."),
            "native": declaration.name,
            "source": identity(declaration),
        }
        if markers := sorted(required_opt_ins(declaration, index)):
            scoped["optIn"] = markers
        if renamed:
            scoped["parameters"] = renamed
        planned[declaration.name].append((scoped, props))
    named = _named(planned, taken, refused)
    return {name: {"since": since, **entry} for name, entry in named.items()}, refused


def _parameters(
    declaration: Declaration, families: dict[str, str], own: dict[str, Any]
) -> dict[str, Any]:
    """Each parameter's binding rule; an optional one that does not bind is left out.

    Args:
        declaration: The scope-declared modifier.
        families: Approved value families, by the classifier they bind.
        own: The declaration's compiler-resolved defaults.

    Returns:
        The planned rules, by parameter name.

    Raises:
        ValueError: A required parameter has no wire binding.
    """
    parameters: dict[str, Any] = {}
    for parameter in declaration.parameters:
        try:
            rule = bind_parameter(parameter, families, own, {})
        except ValueError as exc:
            if parameter.required:
                raise ValueError(f"{parameter.name}: {exc}") from exc
            continue
        parameters[parameter.name] = {
            **rule,
            "type": parameter.type.document,
            "required": parameter.required,
            "hasDefault": parameter.has_default,
        }
    return parameters


def _scope(declaration: Declaration) -> str:
    """The scope a member modifier is declared in: its dispatch receiver."""
    assert declaration.dispatch_receiver is not None, declaration.name
    return declaration.dispatch_receiver.classifier


def _named(
    planned: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]],
    taken: frozenset[str],
    refused: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Wire names: one per native name, or one per scope where props differ."""
    modifiers: dict[str, dict[str, Any]] = {}
    for native, overloads in sorted(planned.items()):
        scopes = [scoped["scope"] for scoped, _ in overloads]
        if len(set(scopes)) != len(scopes):
            refused[native] = "a scope declares several bindable overloads"
            continue
        if all(props == overloads[0][1] for _, props in overloads):
            entries = [(native, overloads[0][1], [scoped for scoped, _ in overloads])]
        else:
            entries = [
                (_prefixed(scoped["scope"], native), props, [scoped])
                for scoped, props in overloads
            ]
        for name, props, scoped_list in entries:
            if name in taken or name in modifiers:
                # Two scopes with one simple name (material's and material3's
                # ExposedDropdownMenuBoxScope) would name one operation twice.
                refused[name] = "the name is ambiguous across scopes or with policy"
                modifiers.pop(name, None)
                taken = taken | {name}
                continue
            modifiers[name] = {"props": props, "scoped": scoped_list}
    return modifiers


def _prefixed(scope: str, native: str) -> str:
    stem = scope.rsplit(".", 1)[-1].removesuffix("Scope")
    return stem[0].lower() + stem[1:] + native[0].upper() + native[1:]


def modifier_props(
    name: str, parameters: dict[str, Any], families: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Derive the props a scope-declared modifier takes, as a component's are.

    Args:
        name: The modifier, for refusal messages.
        parameters: Its planned parameters' rules.
        families: The approved value families, from :func:`family_index`.

    Returns:
        The props by wire name, and the native parameter of each prop whose
        wire name differs from it.

    Raises:
        ValueError: A parameter is a shape a modifier operation cannot carry.
    """
    props: dict[str, Any] = {}
    renamed: dict[str, str] = {}
    for parameter, spec in parameters.items():
        if spec["policy"] not in {"scalar", "value", "omit"}:
            raise ValueError(f"{parameter}: a modifier cannot take a {spec['policy']}")
        if spec["policy"] == "omit":
            continue
        prop = wire_prop(name, parameter, spec, families, [])
        if prop is None:
            continue
        wire = parameter
        if parameter == DISCRIMINATOR:
            # The operation's own "type" key names it; the parameter crosses
            # under its operation's name and binds back by its own.
            wire = name.rsplit(".", 1)[-1] + parameter[:1].upper() + parameter[1:]
            renamed[wire] = parameter
        props[wire] = prop
    return props, renamed
