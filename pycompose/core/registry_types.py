"""Runtime registry types mirroring ``schema/components.json`` (plan 04).

The registry is the single source of truth for which components and actions
exist and what shape their props/payloads take. These frozen, stdlib-only
types are the runtime view consumed by the emitter; :meth:`Registry.from_mapping`
and :meth:`Registry.to_mapping` round-trip the JSON so the file and the types
cannot silently diverge.

The prop-type vocabulary is validated by the codegen tool (``tools/schema``)
and the generated validators; here ``type`` is treated as an opaque string.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from types import MappingProxyType
from typing import Protocol, cast

from pycompose.core.props import JsonValue
from pycompose.errors import ComponentRegistryError
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json, thaw_json

__all__ = [
    "AbstractComponentRegistry",
    "ActionDef",
    "ChildrenRule",
    "ComponentDef",
    "ComponentSpec",
    "ContentSlot",
    "PropDef",
    "Registry",
]

OWNERS = ("python", "host")
"""Who may set a prop. Anything else is refused rather than ignored."""


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
            The slot as it appears in ``components.json``.
        """
        result: dict[str, object] = {"composable": self.composable}
        if self.parameter is not None:
            result["parameter"] = self.parameter
        return result


@dataclass(frozen=True, slots=True)
class PropDef:
    """A prop (or action-payload field) definition.

    Attributes:
        type: The prop type name.
        values: Allowed enum values or resource kinds.
        owner: Who drives the value. ``"python"`` means the app declares it and
            a test can assert on it; ``"host"`` means the host retains it
            between snapshots and the app never sees it -- the ripple behind a
            tap, where a list is scrolled to. This is ADR-0013's question asked
            per prop, so "state-controllable" is checkable rather than implied.
        required: Whether the prop must be present.
        has_default: Whether a default is declared.
        default: The declared default, when ``has_default`` is set.
        minimum: Inclusive lower bound for a numeric prop.
        maximum: Inclusive upper bound for a numeric prop.
        since: First schema exposing the prop, if added after the initial catalog.
        content: Set when the prop was flattened out of a Compose content slot,
            recording which composable wraps it and under what parameter name.
        payload: The arguments a callback prop receives, as ``(name, type)``
            pairs. Compose's ``onClick`` takes none; ``onCheckedChange`` takes
            the new ``value``; ``onValueChange`` takes ``text``. Declared here
            because a component entry cannot otherwise see what its own callback
            is handed, and a generated adapter that omits the argument does not
            compile.
        decode: Which host resolver decodes this prop's value, for the prop
            types whose Kotlin type is not the wire type: ``enum``, ``color``
            and ``resource``. ``PropResolver`` already knows how to turn
            ``"start"`` into an ``Alignment.Horizontal``, but nothing in the
            data says ``['start','center','end']`` means *horizontal* rather
            than some other family with the same three values. Declared per
            prop rather than inferred from the value set, because inference
            breaks silently the day two families share a value set, and the
            failure is a wrong alignment rather than an error.
        value_type: Optional approved native value family for tagged inputs.
        native_default: Native default provider used by generated adapters.
        fallback: Native expression used in place of a decoded prop's per-decoder
            default, for the parameters where the hand-written adapter read the
            theme instead. Only valid together with ``decode``.
        nullable: Whether an explicit null is valid, distinct from absence.
    """

    type: str
    values: tuple[str, ...] = ()
    owner: str = "python"
    required: bool = False
    has_default: bool = False
    default: JsonValue | FrozenJsonValue = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    since: str | None = None
    content: ContentSlot | None = None
    payload: tuple[tuple[str, str], ...] = ()
    decode: str | None = None
    value_type: str | None = None
    native_default: str | None = None
    fallback: str | None = None
    nullable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))
        object.__setattr__(self, "payload", tuple(self.payload))
        if self.content is not None and self.type != "string":
            raise ComponentRegistryError(
                "a content slot must flatten a string prop, " f"not a {self.type} one"
            )
        if self.payload and self.type != "actionId":
            raise ComponentRegistryError(
                "only an actionId prop can declare a callback payload, "
                f"not a {self.type} one"
            )
        for name, kind in self.payload:
            if not name or not kind:
                raise ComponentRegistryError("payload fields need a name and a type")
        if self.since is not None and (
            not isinstance(self.since, str) or not self.since
        ):
            raise ComponentRegistryError("since must be a non-empty schema version")
        object.__setattr__(self, "default", freeze_json(self.default))
        for bound in (self.minimum, self.maximum):
            if bound is not None and (
                not isinstance(bound, int | float)
                or isinstance(bound, bool)
                or (isinstance(bound, float) and not math.isfinite(bound))
            ):
                raise ComponentRegistryError("numeric bounds must be finite numbers")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ComponentRegistryError("minimum exceeds maximum")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, where: str) -> PropDef:
        """Build a :class:`PropDef` from raw JSON.

        Args:
            data: The raw prop object.
            where: Human-readable location for error messages.

        Returns:
            The parsed prop definition.

        Raises:
            ComponentRegistryError: If the prop object is malformed.
        """
        ptype = data.get("type")
        if not isinstance(ptype, str) or not ptype:
            raise ComponentRegistryError(f"{where}: 'type' must be a non-empty string")
        values: tuple[str, ...] = ()
        raw_values = data.get("values")
        if raw_values is not None:
            if not isinstance(raw_values, list) or not all(
                isinstance(value, str) for value in raw_values
            ):
                raise ComponentRegistryError(
                    f"{where}: 'values' must be a list of strings"
                )
            values = tuple(raw_values)
        required = data.get("required", False)
        if not isinstance(required, bool):
            raise ComponentRegistryError(f"{where}: 'required' must be a boolean")
        owner = data.get("owner", "python")
        if owner not in OWNERS:
            raise ComponentRegistryError(
                f"{where}: 'owner' must be one of {', '.join(OWNERS)}"
            )
        return cls(
            type=ptype,
            values=values,
            owner=cast("str", owner),
            required=required,
            has_default="default" in data,
            default=cast("JsonValue", data.get("default")),
            minimum=cast("int | float | None", data.get("minimum")),
            maximum=cast("int | float | None", data.get("maximum")),
            since=cast("str | None", data.get("since")),
            content=_content(data, where),
            payload=_payload(data, where),
            decode=_decode(ptype, cast("str | None", data.get("decode"))),
            value_type=cast("str | None", data.get("valueType")),
            native_default=cast("str | None", data.get("nativeDefault")),
            fallback=cast("str | None", data.get("fallback")),
            nullable=cast("bool", data.get("nullable", False)),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the ``components.json`` prop shape.

        Returns:
            A JSON-ready dict.
        """
        out: dict[str, object] = {"type": self.type}
        out.update(
            {
                key: value
                for key, value in {
                    "valueType": self.value_type,
                    "nativeDefault": self.native_default,
                    "fallback": self.fallback,
                    "nullable": True if self.nullable else None,
                }.items()
                if value is not None
            }
        )
        if self.owner != "python":
            # Absent means python, so the common case costs no bytes.
            out["owner"] = self.owner
        if self.values:
            out["values"] = list(self.values)
        if self.required:
            out["required"] = True
        if self.has_default:
            out["default"] = thaw_json(self.default)
        if self.minimum is not None:
            out["minimum"] = self.minimum
        if self.maximum is not None:
            out["maximum"] = self.maximum
        if self.since is not None:
            out["since"] = self.since
        if self.content is not None:
            out["content"] = self.content.to_mapping()
        if self.payload:
            out["payload"] = [
                {"name": field_name, "type": kind} for field_name, kind in self.payload
            ]
        if self.decode is not None:
            out["decode"] = self.decode
        return out


@dataclass(frozen=True, slots=True)
class ChildrenRule:
    """Rules governing a component's primary (unslotted) child nodes.

    Attributes:
        allowed: Whether children are permitted.
        kind: Optional children kind (e.g. ``content``, ``items``).
        min: Optional minimum child count.
        native: Native parameter name the children are placed in.
        consume: Slot scope the adapter consumes on the children's behalf.
    """

    allowed: bool
    kind: str | None = None
    min: int | None = None
    native: str | None = None
    consume: str | None = None

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
        return cls(
            allowed=allowed,
            kind=kind,
            min=minimum,
            native=native,
            consume=cast("str | None", consume),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the ``components.json`` children shape.

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
    """

    native: str
    kind: str = "content"
    nullable: bool = False
    consume: str | None = None

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
        return cls(
            native=native,
            kind=cast("str", kind),
            nullable=nullable,
            consume=cast("str | None", consume),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the ``components.json`` slot shape.

        Returns:
            A JSON-ready dict.
        """
        out: dict[str, object] = {"native": self.native}
        if self.kind != "content":
            out["kind"] = self.kind
        if self.nullable:
            out["nullable"] = True
        if self.consume is not None:
            out["consume"] = self.consume
        return out


SLOT_KINDS = ("content", "items")
"""How a slot's subtree is composed: nodes in order, or lazy list items."""

CONSUMERS = ("paddingValues",)
"""Slot scopes the adapter consumes on the subtree's behalf.

A consumed scope is never lost: the adapter applies it in the one place Compose
idiomatically applies it, and the app cannot apply it twice.
"""

INTERACTION_KINDS = ("press", "focus", "hover")
"""Interaction kinds the host can observe and report as actions."""


@dataclass(frozen=True, slots=True)
class InteractionRule:
    """The host-created interaction source a component accepts.

    The source is the host's: it is remembered per node id so a snapshot pull
    restarts no ripple in flight, and the observed press state returns as an
    action a frame later rather than driving a same-frame visual.

    Attributes:
        native: Native parameter the remembered source fills.
        observations: One actionId prop per observed interaction kind; each
            prop's payload observes that kind's session state.
    """

    native: str
    observations: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "observations", MappingProxyType(dict(self.observations))
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, where: str) -> InteractionRule:
        """Build a :class:`InteractionRule` from raw JSON.

        Args:
            data: The raw interaction object.
            where: Human-readable location for error messages.

        Returns:
            The parsed interaction rule.

        Raises:
            ComponentRegistryError: If the interaction object is malformed.
        """
        native = data.get("native")
        if not isinstance(native, str) or not native:
            raise ComponentRegistryError(f"{where}: 'native' must be a name")
        raw = data.get("observations")
        if not isinstance(raw, Mapping) or not raw:
            raise ComponentRegistryError(
                f"{where}: 'observations' must be a non-empty object"
            )
        observations: dict[str, str] = {}
        for kind, prop in raw.items():
            if kind not in INTERACTION_KINDS:
                raise ComponentRegistryError(
                    f"{where}: unknown observation {kind!r}; vocabulary: "
                    + ", ".join(INTERACTION_KINDS)
                )
            if not isinstance(prop, str) or not prop:
                raise ComponentRegistryError(
                    f"{where}: observation {kind!r} must name a prop"
                )
            observations[kind] = prop
        return cls(native=native, observations=observations)

    def to_mapping(self) -> dict[str, object]:
        """Render back to the ``components.json`` interaction shape.

        Returns:
            A JSON-ready dict.
        """
        return {"native": self.native, "observations": dict(self.observations)}


class ComponentDef(Protocol):
    """Read-only structural view of a component definition."""

    @property
    def name(self) -> str:
        """Component type name (e.g. ``Button``).

        Returns:
            The component name.
        """
        ...

    @property
    def category(self) -> str:
        """Registry category (e.g. ``buttons``).

        Returns:
            The category name.
        """
        ...

    @property
    def stability(self) -> str:
        """Stability tag (``stable``/``beta``/``experimental``).

        Returns:
            The stability tag.
        """
        ...

    @property
    def props(self) -> Mapping[str, PropDef]:
        """Declared props by wire name.

        Returns:
            The props mapping.
        """
        ...

    @property
    def children(self) -> ChildrenRule:
        """Child-node rules.

        Returns:
            The children rule.
        """
        ...

    @property
    def slots(self) -> Mapping[str, SlotRule]:
        """Named slots by wire name.

        Returns:
            The slot rules.
        """
        ...


ADAPTERS = ("generated", "manual")
"""Whether the Kotlin adapter is derived from the schema or written by hand."""


def _adapter(name: str, value: object) -> str:
    """Parse a component's adapter mode.

    Args:
        name: The component's registry key, for the error message.
        value: The raw ``adapter`` field.

    Returns:
        The adapter mode.

    Raises:
        ComponentRegistryError: If the field is present but unrecognised.
    """
    if value is None:
        return "generated"
    if value not in ADAPTERS:
        raise ComponentRegistryError(
            f"component {name!r}: 'adapter' must be one of {', '.join(ADAPTERS)}"
        )
    return cast("str", value)


DECODED_TYPES = ("enum", "color", "resource")
"""Prop types whose Kotlin type is not the wire type, and so need a decoder."""

DECODERS = (
    "alignment",
    "arrangement",
    "color",
    "horizontal",
    "resourceFont",
    "resourceImage",
    "resourceText",
    "textStyle",
    "vertical",
)
"""The host resolvers a prop may name."""


def _decode(ptype: str, value: str | None) -> str | None:
    """Parse a prop's declared decoder.

    Args:
        ptype: The prop's declared type.
        value: The raw ``decode`` field.

    Returns:
        The decoder name, or None when the prop needs none.

    Raises:
        ComponentRegistryError: If the field is present but unusable.
    """
    if value is None:
        return None
    if ptype not in DECODED_TYPES:
        raise ComponentRegistryError(
            f"only a {', '.join(DECODED_TYPES)} prop can name a decoder, "
            f"not a {ptype} one"
        )
    if value not in DECODERS:
        raise ComponentRegistryError(
            f"'decode' must be one of {', '.join(DECODERS)}, not {value!r}"
        )
    return value


def _content(data: Mapping[str, object], where: str) -> ContentSlot | None:
    """Parse a prop's declared content slot.

    Args:
        data: The raw prop object.
        where: Human-readable location for error messages.

    Returns:
        The parsed slot, or None when the prop is not flattened content.

    Raises:
        ComponentRegistryError: If the slot object is malformed.
    """
    raw = data.get("content")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ComponentRegistryError(f"{where}: 'content' must be an object")
    return ContentSlot.from_mapping(raw, where=where)


def _payload(data: Mapping[str, object], where: str) -> tuple[tuple[str, str], ...]:
    """Parse a callback prop's declared arguments.

    Args:
        data: The raw prop object.
        where: Human-readable location for error messages.

    Returns:
        The arguments as ``(name, type)`` pairs, empty when none are declared.

    Raises:
        ComponentRegistryError: If the payload is malformed.
    """
    raw = data.get("payload")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ComponentRegistryError(f"{where}: 'payload' must be a list")
    fields: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ComponentRegistryError(
                f"{where}: each payload field must be an object"
            )
        field_name = item.get("name")
        kind = item.get("type")
        if not isinstance(field_name, str) or not field_name:
            raise ComponentRegistryError(f"{where}: payload field needs a 'name'")
        if not isinstance(kind, str) or not kind:
            raise ComponentRegistryError(
                f"{where}: payload field {field_name!r} needs a 'type'"
            )
        fields.append((field_name, kind))
    if len({field_name for field_name, _ in fields}) != len(fields):
        raise ComponentRegistryError(f"{where}: payload field names must be unique")
    return tuple(fields)


WRAPPERS = ("ResourceText", "ResourceImage")
"""Composables an adapter may delegate to whole.

A wrapper resolves its content asynchronously -- off the Compose thread, with
its own diagnostics -- so it cannot be expressed as a resolved prop value. The
call site is mechanical; what it delegates to is not.
"""


def _wrapper(name: str, value: object) -> str | None:
    """Parse a component's declared wrapper.

    Args:
        name: The component's registry key, for the error message.
        value: The raw ``wrapper`` field.

    Returns:
        The wrapper's name, or None when the component has none.

    Raises:
        ComponentRegistryError: If the field is present but unrecognised.
    """
    if value is None:
        return None
    if value not in WRAPPERS:
        raise ComponentRegistryError(
            f"component {name!r}: 'wrapper' must be one of {', '.join(WRAPPERS)}"
        )
    return cast("str", value)


def _reshaped(name: str, value: object) -> tuple[str, ...]:
    """Parse a component's declared reshaped props.

    Args:
        name: The component's registry key, for the error message.
        value: The raw ``reshaped`` field.

    Returns:
        The prop names, in declaration order.

    Raises:
        ComponentRegistryError: If the field is present but malformed.
    """
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ComponentRegistryError(
            f"component {name!r}: 'reshaped' must be a string list"
        )
    return tuple(value)


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """Concrete component definition (implements :class:`ComponentDef`).

    Attributes:
        name: Component type name.
        category: Registry category.
        stability: Stability tag.
        props: Declared props by wire name.
        children: Child-node rules.
        since: First schema exposing this component, if not in the initial catalog.
        reshaped: Props PyCompose invented or reshaped, which Compose's
            signature has no counterpart for. Compose has no `Button.text`
            parameter -- text is a content slot there -- and no
            `TextField.selection` at all. Recorded so the drift checker can say
            "deliberate" rather than "removed".
        adapter: ``"manual"`` when the Kotlin adapter cannot be generated. The
            default is to generate it; a component opts out by carrying a
            decision a generator cannot make, and says which.
        wrapper: The hand-written composable this adapter delegates to whole,
            when it has one. Set instead of ``adapter`` because the call site is
            still mechanical -- only the thing it calls is not.
        slots: Named slots by wire name, each reaching its own native parameter.
            Declared rather than inferred: which of a component's content
            parameters a subtree belongs in is a decision the schema owns.
        interaction: The host-created interaction source this component accepts,
            if any. Codegen-only: it says which native parameter the renderer
            fills and which prop observes each interaction kind.
    """

    name: str
    category: str
    stability: str
    props: Mapping[str, PropDef]
    children: ChildrenRule
    since: str | None = None
    reshaped: tuple[str, ...] = ()
    adapter: str = "generated"
    wrapper: str | None = None
    slots: Mapping[str, SlotRule] = dataclass_field(default_factory=dict)
    interaction: InteractionRule | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "props", MappingProxyType(dict(self.props)))
        object.__setattr__(self, "slots", MappingProxyType(dict(self.slots)))
        if self.since is not None and (
            not isinstance(self.since, str) or not self.since
        ):
            raise ComponentRegistryError("since must be a non-empty schema version")

    @classmethod
    def from_mapping(cls, name: str, data: Mapping[str, object]) -> ComponentSpec:
        """Build a :class:`ComponentSpec` from raw JSON.

        Args:
            name: The component's registry key.
            data: The raw component object.

        Returns:
            The parsed component definition.

        Raises:
            ComponentRegistryError: If the component object is malformed.
        """
        category = data.get("category")
        if not isinstance(category, str) or not category:
            raise ComponentRegistryError(
                f"component {name!r}: 'category' must be a non-empty string"
            )
        stability = data.get("stability")
        if not isinstance(stability, str) or not stability:
            raise ComponentRegistryError(
                f"component {name!r}: 'stability' must be a non-empty string"
            )
        raw_props = data.get("props")
        if not isinstance(raw_props, Mapping):
            raise ComponentRegistryError(
                f"component {name!r}: 'props' must be an object"
            )
        props: dict[str, PropDef] = {}
        for prop_name, prop in raw_props.items():
            if not isinstance(prop_name, str) or not isinstance(prop, Mapping):
                raise ComponentRegistryError(
                    f"component {name!r}: prop {prop_name!r} must be an object"
                )
            props[prop_name] = PropDef.from_mapping(prop, where=f"{name}.{prop_name}")
        raw_children = data.get("children")
        if not isinstance(raw_children, Mapping):
            raise ComponentRegistryError(
                f"component {name!r}: 'children' must be an object"
            )
        raw_slots = data.get("slots", {})
        if not isinstance(raw_slots, Mapping):
            raise ComponentRegistryError(
                f"component {name!r}: 'slots' must be an object"
            )
        slots: dict[str, SlotRule] = {}
        for slot_name, slot in raw_slots.items():
            if not isinstance(slot_name, str) or not isinstance(slot, Mapping):
                raise ComponentRegistryError(
                    f"component {name!r}: slot {slot_name!r} must be an object"
                )
            slots[slot_name] = SlotRule.from_mapping(slot, where=f"{name}.{slot_name}")
        raw_interaction = data.get("interaction")
        if raw_interaction is not None and not isinstance(raw_interaction, Mapping):
            raise ComponentRegistryError(
                f"component {name!r}: 'interaction' must be an object"
            )
        interaction = (
            InteractionRule.from_mapping(raw_interaction, where=f"{name}.interaction")
            if isinstance(raw_interaction, Mapping)
            else None
        )
        return cls(
            name=name,
            category=category,
            stability=stability,
            props=props,
            children=ChildrenRule.from_mapping(raw_children, where=f"{name}.children"),
            since=cast("str | None", data.get("since")),
            reshaped=_reshaped(name, data.get("reshaped")),
            adapter=_adapter(name, data.get("adapter")),
            wrapper=_wrapper(name, data.get("wrapper")),
            slots=slots,
            interaction=interaction,
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the ``components.json`` component shape.

        Returns:
            A JSON-ready dict.
        """
        result: dict[str, object] = {
            "category": self.category,
            "stability": self.stability,
            "props": {name: prop.to_mapping() for name, prop in self.props.items()},
            "children": self.children.to_mapping(),
        }
        if self.slots:
            result["slots"] = {
                name: rule.to_mapping() for name, rule in self.slots.items()
            }
        if self.interaction is not None:
            result["interaction"] = self.interaction.to_mapping()
        if self.since is not None:
            result["since"] = self.since
        if self.reshaped:
            result["reshaped"] = list(self.reshaped)
        if self.adapter != "generated":
            result["adapter"] = self.adapter
        if self.wrapper is not None:
            result["wrapper"] = self.wrapper
        return result


@dataclass(frozen=True, slots=True)
class ActionDef:
    """An action definition: its id and typed payload fields.

    Attributes:
        action_id: The ``actionId`` the host sends.
        payload: Payload fields by name.
    """

    action_id: str
    payload: Mapping[str, PropDef]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    @classmethod
    def from_mapping(cls, action_id: str, data: Mapping[str, object]) -> ActionDef:
        """Build an :class:`ActionDef` from raw JSON.

        Args:
            action_id: The action's registry key.
            data: The raw action object.

        Returns:
            The parsed action definition.

        Raises:
            ComponentRegistryError: If the action object is malformed.
        """
        raw_payload = data.get("payload", {})
        if not isinstance(raw_payload, Mapping):
            raise ComponentRegistryError(
                f"action {action_id!r}: 'payload' must be an object"
            )
        payload: dict[str, PropDef] = {}
        for field_name, field in raw_payload.items():
            if not isinstance(field_name, str) or not isinstance(field, Mapping):
                raise ComponentRegistryError(
                    f"action {action_id!r}: payload field {field_name!r} "
                    "must be an object"
                )
            payload[field_name] = PropDef.from_mapping(
                field, where=f"action {action_id}.{field_name}"
            )
        return cls(action_id=action_id, payload=payload)

    def to_mapping(self) -> dict[str, object]:
        """Render back to the ``components.json`` action shape.

        Returns:
            A JSON-ready dict.
        """
        return {
            "payload": {
                name: field.to_mapping() for name, field in self.payload.items()
            }
        }


class AbstractComponentRegistry(ABC):
    """Read-only registry interface: look up components and actions by name."""

    @abstractmethod
    def component(self, name: str) -> ComponentDef:
        """Return the component definition for ``name``.

        Args:
            name: The component name.

        Returns:
            The component definition.
        """
        ...

    @abstractmethod
    def action(self, action_id: str) -> ActionDef:
        """Return the action definition for ``action_id``.

        Args:
            action_id: The action id.

        Returns:
            The action definition.
        """
        ...

    @abstractmethod
    def component_names(self) -> tuple[str, ...]:
        """Return all component names in registry order.

        Returns:
            The component names.
        """
        ...

    @abstractmethod
    def action_ids(self) -> tuple[str, ...]:
        """Return all action ids in registry order.

        Returns:
            The action ids.
        """
        ...


def _value_types(value: object) -> dict[str, Mapping[str, object]]:
    """Parse the declared structured-value encodings.

    Args:
        value: The raw ``valueTypes`` section, absent on older schemas.

    Returns:
        Each family's encoding and shape, by name.

    Raises:
        ComponentRegistryError: If the section is present but malformed.
    """
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ComponentRegistryError("'valueTypes' must be an object")
    families: dict[str, Mapping[str, object]] = {}
    for name, spec in value.items():
        if not isinstance(spec, Mapping):
            raise ComponentRegistryError(f"valueTypes.{name} must be an object")
        families[name] = dict(spec)
    return families


@dataclass(frozen=True, slots=True)
class Registry(AbstractComponentRegistry):
    """Frozen, in-memory view of the component registry.

    Attributes:
        schema_version: The IR contract version (``schemaVersion``).
        min_library_version: The minimum library version required.
        components: Component definitions by name.
        actions: Action definitions by id.
        effects: Effect definitions by kind. Structurally identical to actions:
            the host reads the contract, Python emits the request.
        lifecycle: Host-initiated events by name. Kept apart from actions so a
            component can never bind one to a tap.
        modifiers: Ordered modifier operation definitions by wire name.
        supported_schema_versions: Explicit compatible wire versions, when declared.
        value_types: The declared encodings for structured values, by name.
            Material3 carries thousands of parameters typed ``Color``, ``Dp`` or
            ``Shape``; these say how each family crosses as JSON, so a new
            Compose type costs one entry rather than a new mechanism.
    """

    schema_version: str
    min_library_version: str
    components: Mapping[str, ComponentSpec]
    actions: Mapping[str, ActionDef]
    effects: Mapping[str, ActionDef]
    lifecycle: Mapping[str, ActionDef]
    modifiers: Mapping[str, Mapping[str, PropDef]] = dataclass_field(
        default_factory=dict
    )
    supported_schema_versions: tuple[str, ...] = ()
    value_types: Mapping[str, Mapping[str, object]] = dataclass_field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "value_types", MappingProxyType(dict(self.value_types))
        )
        object.__setattr__(
            self, "supported_schema_versions", tuple(self.supported_schema_versions)
        )
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))
        object.__setattr__(self, "actions", MappingProxyType(dict(self.actions)))
        object.__setattr__(self, "effects", MappingProxyType(dict(self.effects)))
        object.__setattr__(self, "lifecycle", MappingProxyType(dict(self.lifecycle)))
        object.__setattr__(
            self,
            "modifiers",
            MappingProxyType(
                {
                    name: MappingProxyType(dict(props))
                    for name, props in self.modifiers.items()
                }
            ),
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> Registry:
        """Parse a :class:`Registry` from raw ``components.json`` data.

        Args:
            data: The parsed registry JSON.

        Returns:
            The parsed registry.

        Raises:
            ComponentRegistryError: If the registry data is malformed.
        """
        schema_version = data.get("schemaVersion")
        if not isinstance(schema_version, str) or not schema_version:
            raise ComponentRegistryError(
                "registry 'schemaVersion' must be a non-empty string"
            )
        min_library_version = data.get("minLibraryVersion")
        if not isinstance(min_library_version, str) or not min_library_version:
            raise ComponentRegistryError(
                "registry 'minLibraryVersion' must be a non-empty string"
            )
        supported = data.get("supportedSchemaVersions", [])
        if not isinstance(supported, list) or not all(
            isinstance(version, str) and version for version in supported
        ):
            raise ComponentRegistryError(
                "supportedSchemaVersions must be a list of versions"
            )
        if len(set(supported)) != len(supported):
            raise ComponentRegistryError("supportedSchemaVersions must be unique")
        raw_components = data.get("components")
        if not isinstance(raw_components, Mapping) or not raw_components:
            raise ComponentRegistryError(
                "registry 'components' must be a non-empty object"
            )
        components: dict[str, ComponentSpec] = {}
        for name, body in raw_components.items():
            if not isinstance(name, str) or not isinstance(body, Mapping):
                raise ComponentRegistryError(f"component {name!r} must be an object")
            components[name] = ComponentSpec.from_mapping(name, body)
        raw_actions = data.get("actions")
        if not isinstance(raw_actions, Mapping):
            raise ComponentRegistryError("registry 'actions' must be an object")
        actions: dict[str, ActionDef] = {}
        for action_id, body in raw_actions.items():
            if not isinstance(action_id, str) or not isinstance(body, Mapping):
                raise ComponentRegistryError(f"action {action_id!r} must be an object")
            actions[action_id] = ActionDef.from_mapping(action_id, body)
        effects = _contracts(data, "effects")
        lifecycle = _contracts(data, "lifecycle")
        return cls(
            schema_version=schema_version,
            min_library_version=min_library_version,
            components=components,
            actions=actions,
            effects=effects,
            lifecycle=lifecycle,
            modifiers=_parse_modifiers(data.get("modifiers", {})),
            supported_schema_versions=tuple(supported),
            value_types=_value_types(data.get("valueTypes")),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the ``components.json`` shape.

        Returns:
            A JSON-ready dict matching the registry file.
        """
        result: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "minLibraryVersion": self.min_library_version,
            "components": {
                name: component.to_mapping()
                for name, component in self.components.items()
            },
            "actions": {
                action_id: action.to_mapping()
                for action_id, action in self.actions.items()
            },
            "effects": {
                kind: effect.to_mapping() for kind, effect in self.effects.items()
            },
            "lifecycle": {
                event: lifecycle.to_mapping()
                for event, lifecycle in self.lifecycle.items()
            },
        }
        if self.modifiers:
            result["modifiers"] = {
                name: {"props": {key: prop.to_mapping() for key, prop in props.items()}}
                for name, props in self.modifiers.items()
            }
        if self.supported_schema_versions:
            result["supportedSchemaVersions"] = list(self.supported_schema_versions)
        if self.value_types:
            result["valueTypes"] = {
                name: dict(spec) for name, spec in self.value_types.items()
            }
        return result

    def component(self, name: str) -> ComponentDef:
        """Return the component definition for ``name``.

        Args:
            name: The component name.

        Returns:
            The component definition.

        Raises:
            ComponentRegistryError: If the component is not registered.
        """
        try:
            return self.components[name]
        except KeyError:
            raise ComponentRegistryError("unknown component", component=name) from None

    def action(self, action_id: str) -> ActionDef:
        """Return the action definition for ``action_id``.

        Args:
            action_id: The action id.

        Returns:
            The action definition.

        Raises:
            ComponentRegistryError: If the action is not registered.
        """
        try:
            return self.actions[action_id]
        except KeyError:
            raise ComponentRegistryError("unknown action", action=action_id) from None

    def component_names(self) -> tuple[str, ...]:
        """Return all component names in registry order.

        Returns:
            The component names.
        """
        return tuple(self.components)

    def action_ids(self) -> tuple[str, ...]:
        """Return all action ids in registry order.

        Returns:
            The action ids.
        """
        return tuple(self.actions)


def _contracts(data: Mapping[str, object], field: str) -> dict[str, ActionDef]:
    """Parse one id-to-payload table that shares the action contract shape.

    Args:
        data: The parsed registry JSON.
        field: Table name used in diagnostics.

    Returns:
        The parsed contracts, empty when the table is absent.

    Raises:
        ComponentRegistryError: If the table or any entry is malformed.
    """
    raw = data.get(field, {})
    if not isinstance(raw, Mapping):
        raise ComponentRegistryError(f"registry {field!r} must be an object")
    result: dict[str, ActionDef] = {}
    for name, body in raw.items():
        if not isinstance(name, str) or not isinstance(body, Mapping):
            raise ComponentRegistryError(f"{field} {name!r} must be an object")
        result[name] = ActionDef.from_mapping(name, body)
    return result


def _parse_modifiers(raw: object) -> Mapping[str, Mapping[str, PropDef]]:
    if not isinstance(raw, Mapping):
        raise ComponentRegistryError("registry 'modifiers' must be an object")
    modifiers: dict[str, Mapping[str, PropDef]] = {}
    for name, body in raw.items():
        if not isinstance(name, str) or not isinstance(body, Mapping):
            raise ComponentRegistryError("invalid modifier definition")
        raw_props = body.get("props")
        if not isinstance(raw_props, Mapping):
            raise ComponentRegistryError(
                "modifier 'props' must be an object", modifier=name
            )
        parsed: dict[str, PropDef] = {}
        for prop_name, prop in raw_props.items():
            if not isinstance(prop_name, str) or not isinstance(prop, Mapping):
                raise ComponentRegistryError("invalid modifier prop", modifier=name)
            parsed[prop_name] = PropDef.from_mapping(prop, where=f"{name}.{prop_name}")
        modifiers[name] = parsed
    return modifiers
