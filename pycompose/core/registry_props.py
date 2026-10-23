"""Property-backed rule types of the component registry.

:class:`PropDef` is the widest single type in the registry: one frozen
data class covering plain, bounded, content-flattened, callback and
provider props. It parses through :func:`_content`, :func:`_payload` and
:func:`_decode`. The host-led interaction and state rules live here too:
they sit at the same recursion depth underneath a component definition.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from pycompose.core.props import JsonValue
from pycompose.core.registry_elements import ContentSlot, ProviderDef
from pycompose.core.registry_vocabulary import (
    DECODED_TYPES,
    DECODERS,
    INTERACTION_KINDS,
    OWNERS,
    STATE_KINDS,
)
from pycompose.errors import ComponentRegistryError
from pycompose.utils.json_canonical import FrozenJsonValue, freeze_json, thaw_json


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
        native_type: The narrower native Kotlin type when the wire type is
            wider, as with ``Int`` integer props; None means the wire type is
            already native.
        fallback: Native expression used in place of a decoded prop's per-decoder
            default, for the parameters where the hand-written adapter read the
            theme instead. Only valid together with ``decode``.
        nullable: Whether an explicit null is valid, distinct from absence.
        provider: Set when the prop reaches a native zero-arg lambda parameter.
            The app states a value; the host supplies the function, so the
            parameter stays something the app cannot name (ADR-0016).
        protocol: The protocol mechanism a prop belongs to, such as
            ``window``, for a prop no native parameter receives and no app
            states directly.
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
    native_type: str | None = None
    fallback: str | None = None
    nullable: bool = False
    provider: ProviderDef | None = None
    protocol: str | None = None

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
        if self.provider is not None and self.nullable:
            # The lambda always returns a value; a prop that may be absent has
            # no value for it to return.
            raise ComponentRegistryError("a provider prop cannot be nullable")

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
        raw_provider = data.get("provider")
        if raw_provider is not None and not isinstance(raw_provider, Mapping):
            raise ComponentRegistryError(f"{where}: 'provider' must be an object")
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
            native_type=cast("str | None", data.get("nativeType")),
            fallback=cast("str | None", data.get("fallback")),
            nullable=cast("bool", data.get("nullable", False)),
            provider=(
                ProviderDef.from_mapping(raw_provider, where=where)
                if isinstance(raw_provider, Mapping)
                else None
            ),
            protocol=cast("str | None", data.get("protocol")),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the catalog lock prop shape.

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
                    "nativeType": self.native_type,
                    "fallback": self.fallback,
                    "nullable": True if self.nullable else None,
                    "protocol": self.protocol,
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
        if self.provider is not None:
            out["provider"] = self.provider.to_mapping()
        return out


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
        """Render back to the catalog lock interaction shape.

        Returns:
            A JSON-ready dict.
        """
        return {"native": self.native, "observations": dict(self.observations)}


@dataclass(frozen=True, slots=True)
class StateRule:
    """The host-owned state holder a component accepts.

    The holder is the host's: it is created per stable node id, so pulling a
    snapshot re-renders the tree without recreating state a gesture is already
    moving. Python states the desired value in the snapshot; the host drives
    the holder towards it and reports settled changes back as actions, rather
    than both sides writing the same state.

    Attributes:
        native: Native parameter the remembered holder fills.
        kind: State family, naming the host's create/drive/report logic.
        value: Prop carrying the desired state; absent drives nothing.
        report: ActionId prop reporting settled changes; absent reports nothing.
        dismiss: Native parameter through which the component announces a
            dismissal it has already carried out, if it has one.
    """

    native: str
    kind: str
    value: str
    report: str
    dismiss: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, object], *, where: str) -> StateRule:
        """Build a :class:`StateRule` from raw JSON.

        Args:
            data: The raw state object.
            where: Human-readable location for error messages.

        Returns:
            The parsed state rule.

        Raises:
            ComponentRegistryError: If the state object is malformed.
        """
        native = data.get("native")
        if not isinstance(native, str) or not native:
            raise ComponentRegistryError(f"{where}: 'native' must be a name")
        kind = data.get("kind")
        if not isinstance(kind, str) or kind not in STATE_KINDS:
            raise ComponentRegistryError(
                f"{where}: unknown state kind {kind!r}; vocabulary: "
                + ", ".join(STATE_KINDS)
            )
        names: dict[str, str] = {}
        for field_name in ("value", "report"):
            prop = data.get(field_name)
            if not isinstance(prop, str) or not prop:
                raise ComponentRegistryError(
                    f"{where}: {field_name!r} must name a prop"
                )
            names[field_name] = prop
        dismiss = data.get("dismiss")
        if dismiss is not None and (not isinstance(dismiss, str) or not dismiss):
            raise ComponentRegistryError(f"{where}: 'dismiss' must be a name")
        return cls(
            native=native,
            kind=kind,
            value=names["value"],
            report=names["report"],
            dismiss=dismiss if isinstance(dismiss, str) else None,
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the catalog lock state shape.

        Returns:
            A JSON-ready dict.
        """
        result: dict[str, object] = {
            "native": self.native,
            "kind": self.kind,
            "value": self.value,
            "report": self.report,
        }
        if self.dismiss is not None:
            result["dismiss"] = self.dismiss
        return result
