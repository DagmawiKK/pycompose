"""Which opt-in markers a pinned declaration needs, and which a caller can grant.

An experimental Compose API carries a marker its callers must opt in to; a
generated call names every marker its target, its parameter types and their
defaults need. A marker the pin does not expose cannot be granted outside it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

from pycompose_codegen.derive.classpath_types import Declaration, Inventory, KotlinType


def opt_in_markers(found: Inventory) -> set[str]:
    """Report every opt-in annotation the pin itself declares.

    The set is derived from the artifact, never listed by hand: an annotation
    class only counts when the pinned compiler says it is annotated with
    ``kotlin.RequiresOptIn``.

    Args:
        found: The validated inventory of the current pin.

    Returns:
        The fully qualified, dotted annotation classes the pin declares.
    """
    return {
        declaration.owner
        for declaration in found.declarations
        if declaration.document.get("classKind") == "ANNOTATION_CLASS"
        and "kotlin/RequiresOptIn" in declaration.annotations
    }


def _signature_types(declaration: Declaration) -> Iterator[KotlinType]:
    """Yield every type reachable from one declaration's signature.

    Parameters, receivers and the return type are walked, then generic
    arguments and aliases of each, because an experimental type nested in a
    signature still gates the call site.
    """
    pending = [declaration.return_type]
    for parameter in declaration.parameters:
        pending.append(parameter.type)
        if parameter.vararg_type is not None:
            pending.append(parameter.vararg_type)
    pending.extend(
        receiver
        for receiver in (
            declaration.receiver,
            declaration.dispatch_receiver,
            *declaration.context_receivers,
        )
        if receiver is not None
    )
    seen: set[int] = set()
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        yield value
        for _, argument in value.arguments:
            if argument is not None:
                pending.append(argument)
        pending.extend(
            nested
            for nested in (
                value.abbreviated_type,
                value.outer_type,
                value.flexible_upper_bound,
            )
            if nested is not None
        )


@dataclass(frozen=True)
class OptInIndex:
    """The pin's opt-in markers and the classes that carry one.

    A call site needs opt-in when the declaration is annotated with a marker
    *or* when a type in its signature is: the compiler flags both, and the
    M3 1.4.0 app-bar overloads proved the second half is real (their
    ``scrollBehavior`` parameter type is ``@ExperimentalMaterial3Api`` while
    the functions themselves are unannotated).

    ``inaccessible`` lists markers declared non-public: callers outside the
    library cannot name them in ``@OptIn``, so a declaration gated by one is
    not renderable and must fail closed instead of emitting uncompilable code.
    """

    markers: frozenset[str] = frozenset()
    types: Mapping[str, frozenset[str]] = field(default_factory=dict)
    inaccessible: frozenset[str] = frozenset()

    def of(self, declaration: Declaration) -> set[str]:
        """Report the markers a native call to one declaration must opt in to.

        Args:
            declaration: One pinned declaration.

        Returns:
            The dotted markers a native call site must opt in to.
        """
        markers = {name.replace("/", ".") for name in declaration.annotations}
        required = {name for name in markers if name in self.markers}
        for value in _signature_types(declaration):
            required |= self.types.get(value.classifier.replace("/", "."), frozenset())
        return required


def opt_in_index(found: Inventory) -> OptInIndex:
    """Build the pin's opt-in index, markers plus every carrying type.

    Args:
        found: The validated inventory of the current pin.

    Returns:
        The index a proposal or native call renders its ``@OptIn`` from.
    """
    markers = opt_in_markers(found)
    classes = {klass.owner: klass for klass in found.classes}
    carried: dict[str, frozenset[str]] = {}

    def of_type(owner: str, seen: frozenset[str]) -> frozenset[str]:
        cached = carried.get(owner)
        if cached is not None:
            return cached
        if owner in seen:
            return frozenset()
        klass = classes.get(owner)
        if klass is None:
            return frozenset()
        marks = {
            name.replace("/", ".")
            for name in klass.document["annotations"]
            if name.replace("/", ".") in markers
        }
        for supertype in klass.supertypes:
            marks |= of_type(supertype.replace("/", "."), seen | {owner})
        carried[owner] = frozenset(marks)
        return carried[owner]

    for klass in found.classes:
        of_type(klass.owner, frozenset())
    visibility = {klass.owner: klass.visibility for klass in found.classes}
    inaccessible = frozenset(
        marker for marker in markers if visibility.get(marker) not in (None, "PUBLIC")
    )
    return OptInIndex(
        markers=frozenset(markers), types=carried, inaccessible=inaccessible
    )


def required_opt_ins(declaration: Declaration, index: OptInIndex) -> set[str]:
    """Report which of a declaration's evidence needs an opt-in.

    Args:
        declaration: One pinned declaration.
        index: The pin's opt-in index.

    Returns:
        The dotted markers a native call site must opt in to.
    """
    return index.of(declaration)
