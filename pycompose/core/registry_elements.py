"""Structural leaf types of the component registry.

:class:`ContentSlot` flattens a Compose content lambda back into a prop;
:class:`ProviderDef` records a zero-arg lambda parameter;
:class:`ChildrenRule` and :class:`SlotRule` say where a component's
subtrees compose and which scope each carries. These are the shapes every
outer parsed level references; prop definitions live in
``registry_props`` and component definitions in
``registry_component``, so the import chain here has nothing above leaves
except the vocabulary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from pycompose.core.registry_vocabulary import CONSUMERS, SCOPES, SLOT_KINDS
from pycompose.errors import ComponentRegistryError


@dataclass(frozen=True, slots=True)
class ContentSlot:
    """A scalar prop flattened out of a Compose content slot.

    Compose has no ``Button.text``: text arrives as a content lambda. PyCompose
    flattens it into a prop, which is a reshaping, and this records how to put it
    back -- which composable wraps the value, and whether it goes in a named
    parameter or a trailing lambda.

    Without this, a generated adapter passes ``text = ...`` to a composable with
    no such parameter and the compiler says no. The failure is loud, but only
    after someone waits for a Gradle run to find out.

    Attributes:
        composable: The Compose composable wrapping the value, such as
            ``Text``.
        parameter: The named content parameter to pass, or ``None`` for a
            trailing lambda. ``FilterChip`` names it ``label``; ``Button`` takes
            it positionally.
    """

    composable: str
    parameter: str | None = None

    def __post_init__(self) -> None:
        if not self.composable:
            raise ComponentRegistryError("content slot needs a composable")
        if self.parameter is not None and not self.parameter:
            raise ComponentRegistryError("content parameter must be a name or null")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, where: str) -> ContentSlot:
        """Build a :class:`ContentSlot` from raw JSON.

        Args:
            data: The raw ``content`` object.
            where: Human-readable location for error messages.

        Returns:
            The parsed content slot.

        Raises:
            ComponentRegistryError: If the object is malformed.
        """
        composable = data.get("composable")
        if not isinstance(composable, str) or not composable:
            raise ComponentRegistryError(
                f"{where}: 'content.composable' must be a non-empty string"
            )
        parameter = data.get("parameter")
        if parameter is not None and (not isinstance(parameter, str) or not parameter):
            raise ComponentRegistryError(
                f"{where}: 'content.parameter' must be a non-empty string or null"
            )
        return cls(composable=composable, parameter=parameter)

    def to_mapping(self) -> dict[str, object]:
        """Render as a plain JSON object.

        Returns:
            The slot as it appears in the catalog lock.
        """
        result: dict[str, object] = {"composable": self.composable}
        if self.parameter is not None:
            result["parameter"] = self.parameter
        return result


@dataclass(frozen=True, slots=True)
class ProviderDef:
    """A prop the native call receives as a zero-arg lambda.

    Attributes:
        native: The pinned parameter the host fills during composition.
        returns: The lambda's pinned return type. Recorded so a generated
            adapter can coerce the wire value instead of guessing, and so the
            drift check can re-derive it from the pinned declaration.
    """

    native: str
    returns: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, where: str) -> ProviderDef:
        """Build a :class:`ProviderDef` from raw JSON.

        Args:
            data: The raw ``provider`` object.
            where: Human-readable location for error messages.

        Returns:
            The parsed provider definition.

        Raises:
            ComponentRegistryError: If the provider object is malformed.
        """
        native = data.get("native")
        if not isinstance(native, str) or not native:
            raise ComponentRegistryError(
                f"{where}: provider 'native' must be a parameter name"
            )
        returns = data.get("returns")
        if not isinstance(returns, str) or not returns:
            raise ComponentRegistryError(
                f"{where}: provider 'returns' must be a Kotlin type name"
            )
        return cls(native=native, returns=returns)

    def to_mapping(self) -> dict[str, object]:
        """Render back to the the catalog lock provider shape.

        Returns:
            A JSON-ready dict.
        """
        return {"native": self.native, "returns": self.returns}


@dataclass(frozen=True, slots=True)
class ChildrenRule:
    """Rules governing a component's primary (unslotted) child nodes.

    Attributes:
        allowed: Whether children are permitted.
        kind: Optional children kind (e.g. ``content``, ``items``).
        min: Optional minimum child count.
        native: Native parameter name the children are placed in.
        consume: Slot scope the adapter consumes on the children's behalf.
        provides: Composition scope the children are composed under, when the
            pinned content lambda carries one. Codegen-only: the renderer hands
            the receiver down so a scoped child composes under its provider.
    """

    allowed: bool
    kind: str | None = None
    min: int | None = None
    native: str | None = None
    consume: str | None = None
    provides: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, where: str) -> ChildrenRule:
        """Build a :class:`ChildrenRule` from raw JSON.

        Args:
            data: The raw children object.
            where: Human-readable location for error messages.

        Returns:
            The parsed children rule.

        Raises:
            ComponentRegistryError: If the children object is malformed.
        """
        allowed = data.get("allowed")
        if not isinstance(allowed, bool):
            raise ComponentRegistryError(f"{where}: 'allowed' must be a boolean")
        kind = data.get("kind")
        if kind is not None and not isinstance(kind, str):
            raise ComponentRegistryError(f"{where}: 'kind' must be a string")
        minimum = data.get("min")
        if minimum is not None and (
            not isinstance(minimum, int) or isinstance(minimum, bool)
        ):
            raise ComponentRegistryError(f"{where}: 'min' must be an integer")
        native = data.get("native")
        if native is not None and (not isinstance(native, str) or not native):
            raise ComponentRegistryError(f"{where}: 'native' must be a name")
        consume = data.get("consume")
        if consume is not None and consume not in CONSUMERS:
            raise ComponentRegistryError(
                f"{where}: 'consume' must be one of {', '.join(CONSUMERS)}"
            )
        provides = data.get("provides")
        if provides is not None and provides not in SCOPES:
            raise ComponentRegistryError(
                f"{where}: 'provides' must be one of {', '.join(SCOPES)}"
            )
        return cls(
            allowed=allowed,
            kind=kind,
            min=minimum,
            native=native,
            consume=cast("str | None", consume),
            provides=cast("str | None", provides),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the the catalog lock children shape.

        Returns:
            A JSON-ready dict.
        """
        out: dict[str, object] = {"allowed": self.allowed}
        if self.kind is not None:
            out["kind"] = self.kind
        if self.min is not None:
            out["min"] = self.min
        if self.native is not None:
            out["native"] = self.native
        if self.consume is not None:
            out["consume"] = self.consume
        if self.provides is not None:
            out["provides"] = self.provides
        return out


@dataclass(frozen=True, slots=True)
class SlotRule:
    """One named slot: where a subtree goes and what it carries.

    Attributes:
        native: Native parameter name the subtree is composed in.
        kind: Slot kind (``content`` composes nodes, ``items`` lists them).
        nullable: Whether the native parameter accepts null, so an empty slot
            is omitted instead of composed empty.
        consume: Slot scope the adapter consumes on the subtree's behalf.
        provides: Composition scope the pinned slot lambda carries, handed to
            the children so a scoped child composes under its provider.
        host: Whether the host composes the slot with this node's native
            state instead of passing it to a native parameter. A host slot
            carries no native policy at all.
    """

    native: str | None
    kind: str = "content"
    nullable: bool = False
    consume: str | None = None
    provides: str | None = None
    host: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, where: str) -> SlotRule:
        """Build a :class:`SlotRule` from raw JSON.

        Args:
            data: The raw slot object.
            where: Human-readable location for error messages.

        Returns:
            The parsed slot rule.

        Raises:
            ComponentRegistryError: If the slot object is malformed.
        """
        native = data.get("native")
        if "host" in data:
            if data.get("host") is not True or set(data) != {"host"}:
                raise ComponentRegistryError(
                    f"{where}: a host slot has no native policy"
                )
            return cls(native=None, host=True)
        if not isinstance(native, str) or not native:
            raise ComponentRegistryError(f"{where}: 'native' must be a name")
        kind = data.get("kind", "content")
        if kind not in SLOT_KINDS:
            raise ComponentRegistryError(
                f"{where}: 'kind' must be one of {', '.join(SLOT_KINDS)}"
            )
        nullable = data.get("nullable", False)
        if not isinstance(nullable, bool):
            raise ComponentRegistryError(f"{where}: 'nullable' must be a boolean")
        consume = data.get("consume")
        if consume is not None and consume not in CONSUMERS:
            raise ComponentRegistryError(
                f"{where}: 'consume' must be one of {', '.join(CONSUMERS)}"
            )
        provides = data.get("provides")
        if provides is not None and provides not in SCOPES:
            raise ComponentRegistryError(
                f"{where}: 'provides' must be one of {', '.join(SCOPES)}"
            )
        return cls(
            native=native,
            kind=cast("str", kind),
            nullable=nullable,
            consume=cast("str | None", consume),
            provides=cast("str | None", provides),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the the catalog lock slot shape.

        Returns:
            A JSON-ready dict.
        """
        if self.host:
            return {"host": True}
        out: dict[str, object] = {"native": self.native}
        if self.kind != "content":
            out["kind"] = self.kind
        if self.nullable:
            out["nullable"] = True
        if self.consume is not None:
            out["consume"] = self.consume
        if self.provides is not None:
            out["provides"] = self.provides
        return out
