"""The block overloads: a prop read in the phase the pin defers it to.

Two shapes are not a plain call:

* A block overload whose receiver declares the props as members sets them
  (``graphicsLayer``, and ``semantics``).
* A block overload whose lambda returns a value takes the props through the
  pin's own function making that value (``offset`` returns an ``IntOffset``).

A block that only sets members is read while drawing; one that answers where
the node goes is read in layout. Either form is preferred over a direct call,
because a bound prop read there invalidates that phase alone. A block on a
scope Compose does not invoke per frame -- one that is not a ``Density`` --
offers no binding at all.
"""

from __future__ import annotations

from typing import Any

from pycompose_codegen.derive.classpath_dump import Declaration, Inventory, Parameter
from pycompose_codegen.derive.converters import stated_type
from pycompose_codegen.derive.core_binding import accepts, candidates, dotted, pascal
from pycompose_codegen.derive.propose import identity

DENSITY = "androidx/compose/ui/unit/Density"
UNIT = "kotlin/Unit"
EXTENSION = "kotlin/ExtensionFunctionType"


def _members(found: Inventory, receiver: str) -> dict[str, Declaration]:
    """The members a block's receiver carries, by name.

    A scope states its own members (``GraphicsLayerScope.alpha``) and takes
    extensions on it (``SemanticsPropertyReceiver.contentDescription``); both
    are the prop names a block sets.
    """
    wanted = dotted(receiver)
    return {
        d.name: d
        for d in found.declarations
        if (d.receiver is not None and dotted(d.receiver.classifier) == wanted)
        or (d.receiver is None and dotted(d.owner) == wanted)
    }


def _graphics_scope(found: Inventory, receiver: str) -> bool:
    """Whether a block's receiver is a scope Compose invokes while it draws.

    A block that draws needs units, so its scope is a ``Density``;
    ``GraphicsLayerScope`` is one. A scope that is not (``SemanticsPropertyReceiver``)
    is invoked when Compose collects what it holds, not per frame, so a binding
    read there would never be kept.
    """
    parents = {
        dotted(item.classifier): {dotted(parent) for parent in item.supertypes}
        for item in found.classes
    }
    wanted = dotted(receiver)
    seen = {wanted}
    pending = [wanted]
    while pending:
        current = pending.pop()
        if current == dotted(DENSITY):
            return True
        for parent in parents.get(current, ()):
            if parent not in seen:
                seen.add(parent)
                pending.append(parent)
    return False


def _constants(found: Inventory, owner: str) -> frozenset[str]:
    """The companion constants ``owner`` declares."""
    companion = f"{dotted(owner)}$Companion"
    return frozenset(d.name for d in found.declarations if d.owner == companion)


def _block_parameter(declaration: Declaration) -> Parameter | None:
    """The overload's one required extension-lambda parameter, when it has one."""
    blocks = [
        p
        for p in declaration.parameters
        if not p.has_default and EXTENSION in p.type.annotations
    ]
    rest = [p for p in declaration.parameters if p not in blocks]
    if len(blocks) != 1 or any(not p.has_default for p in rest):
        return None
    return blocks[0]


def _deferred(
    props: dict[str, Any],
    declaration: Declaration,
    found: Inventory,
) -> Parameter | None:
    """The block parameter of an overload the props are the receiver's members of."""
    block = _block_parameter(declaration)
    if block is None:
        return None
    receiver = block.type.arguments[0][1]
    if receiver is None:
        return None
    if all(prop in _members(found, receiver.classifier) for prop in props):
        return block
    return None


def _answering(declaration: Declaration) -> Parameter | None:
    """The block parameter of an overload whose lambda returns a value."""
    block = _block_parameter(declaration)
    if block is None or len(block.type.arguments) < 2:
        return None
    returned = block.type.arguments[1][1]
    if returned is None or returned.classifier == UNIT:
        return None
    return block


def _block(
    name: str,
    props: dict[str, Any],
    declaration: Declaration,
    block: Parameter,
    found: Inventory,
    families: dict[str, Any],
) -> dict[str, Any]:
    """The receiver-block form of a call: every prop is one of its members.

    Args:
        name: The policy modifier's wire name.
        props: Its props, by wire name.
        declaration: The overload the pin offers.
        block: Its one required extension-lambda parameter.
        found: The pinned inventory.
        families: Approved value families, by family name.

    Returns:
        The call, with each prop bound to a member of the block's receiver.

    Raises:
        ValueError: If a prop is not a settable member of the receiver's type.
    """
    receiver = block.type.arguments[0][1]
    if receiver is None:
        raise ValueError(f"{name}: the block declares no receiver")
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
            "type": dotted(classifier),
            "source": identity(member),
        }
        if spec["type"] == "enum":
            declared = _constants(found, classifier)
            wanted = {value: pascal(value) for value in spec["values"]}
            missing = sorted(v for v, c in wanted.items() if c not in declared)
            if missing:
                raise ValueError(f"{name}.{prop}: no constant for {missing}")
            entry["constants"] = wanted
        elif not accepts(spec, classifier, families):
            raise ValueError(f"{name}.{prop}: {prop!r} takes {dotted(classifier)}")
        arguments[prop] = entry
    return {
        "function": f"{declaration.package}.{declaration.name}",
        "source": identity(declaration),
        "block": {
            "parameter": block.name,
            "receiver": dotted(receiver.classifier),
        },
        "arguments": arguments,
        "phase": (
            "draw" if _graphics_scope(found, receiver.classifier) else "composition"
        ),
    }


def _conversion(
    found: Inventory, receiver: str, source: str, target: str
) -> str | None:
    """A no-argument member of the block's receiver turning ``source`` into ``target``.

    ``Density`` declares ``Dp.roundToPx(): Int``, so a dp prop fills an ``Int``
    parameter inside ``offset { }``. The pin states the conversion; nothing here
    names it.
    """
    for declaration in found.declarations:
        if dotted(declaration.owner) != dotted(receiver):
            continue
        if declaration.receiver is None:
            continue
        if declaration.receiver.classifier != source.replace(".", "/"):
            continue
        if declaration.parameters:
            continue
        if declaration.return_type.classifier == target.replace(".", "/"):
            return declaration.name
    return None


def _result(
    props: dict[str, Any],
    declaration: Declaration,
    block: Parameter,
    found: Inventory,
    families: dict[str, Any],
) -> dict[str, Any] | None:
    """The block form whose lambda returns a value the props make.

    ``offset(offset: Density.() -> IntOffset)`` returns where the node goes, and
    the pin's ``IntOffset(x: Int, y: Int)`` makes it from the props. A prop of
    another type converts through a member of the block's receiver.
    """
    receiver = block.type.arguments[0][1]
    returned = block.type.arguments[1][1]
    if receiver is None or returned is None or returned.classifier == UNIT:
        return None
    for factory in found.declarations:
        if factory.return_type.classifier != returned.classifier:
            continue
        if factory.document.get("visibility") != "PUBLIC":
            continue
        if factory.receiver is not None or factory.dispatch_receiver is not None:
            # A top-level function is callable by its simple name; a member of
            # the value class is not what builds one.
            continue
        if {p.name for p in factory.parameters} != set(props):
            continue
        arguments = _factory_arguments(
            props, factory, receiver.classifier, found, families
        )
        if arguments is None:
            return None
        return {
            "function": f"{declaration.package}.{declaration.name}",
            "source": identity(declaration),
            "block": {
                "parameter": block.name,
                "receiver": dotted(receiver.classifier),
                "result": {
                    "function": f"{factory.package}.{factory.name}",
                    "source": identity(factory),
                    "arguments": arguments,
                },
            },
            "phase": "layout",
        }
    return None


def _factory_arguments(
    props: dict[str, Any],
    factory: Declaration,
    receiver: str,
    found: Inventory,
    families: dict[str, Any],
) -> dict[str, Any] | None:
    """Each prop as the factory's parameter of its name, with its conversion."""
    arguments: dict[str, Any] = {}
    for parameter in factory.parameters:
        spec = props[parameter.name]
        target = dotted(parameter.type.classifier)
        entry: dict[str, Any] = {"parameter": parameter.name, "type": target}
        if not accepts(spec, parameter.type.classifier, families):
            source = stated_type(spec, families)
            convert = (
                None if source is None else _conversion(found, receiver, source, target)
            )
            if convert is None:
                return None
            entry["convert"] = convert
        arguments[parameter.name] = entry
    return arguments


def deferred_call(
    name: str,
    props: dict[str, Any],
    found: Inventory,
    families: dict[str, Any],
) -> dict[str, Any] | None:
    """The deferred form of one modifier's call, when the pin offers one.

    A member block is preferred: Compose invokes it in the phase it runs in,
    which is the closest to the drawing. The answering block comes next.

    Args:
        name: The policy modifier's wire name.
        props: Its props, by wire name.
        found: The pinned inventory.
        families: Approved value families, by family name.

    Returns:
        The call, or None when no block overload defers these props.
    """
    overloads = candidates(found, name)
    for declaration in overloads:
        block = _deferred(props, declaration, found)
        if block is not None:
            return _block(name, props, declaration, block, found, families)
    for declaration in overloads:
        answering = _answering(declaration)
        if answering is not None:
            call = _result(props, declaration, answering, found, families)
            if call is not None:
                return call
    return None
