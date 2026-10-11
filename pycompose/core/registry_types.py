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
    "PropDef",
    "Registry",
]


@dataclass(frozen=True, slots=True)
class PropDef:
    """A prop (or action-payload field) definition.

    Attributes:
        type: The prop type name (opaque here; see the codegen tool).
        values: Allowed values for ``enum`` props.
        required: Whether the prop must be present.
        has_default: Whether a default is declared.
        default: The declared default, when ``has_default`` is set.
        minimum: Inclusive lower bound for a numeric prop.
        maximum: Inclusive upper bound for a numeric prop.
    """

    type: str
    values: tuple[str, ...] = ()
    required: bool = False
    has_default: bool = False
    default: JsonValue | FrozenJsonValue = None
    minimum: int | float | None = None
    maximum: int | float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))
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
        return cls(
            type=ptype,
            values=values,
            required=required,
            has_default="default" in data,
            default=cast("JsonValue", data.get("default")),
            minimum=cast("int | float | None", data.get("minimum")),
            maximum=cast("int | float | None", data.get("maximum")),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the ``components.json`` prop shape.

        Returns:
            A JSON-ready dict.
        """
        out: dict[str, object] = {"type": self.type}
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
        return out


@dataclass(frozen=True, slots=True)
class ChildrenRule:
    """Rules governing a component's child nodes.

    Attributes:
        allowed: Whether children are permitted.
        kind: Optional children kind (e.g. ``content``, ``items``).
        min: Optional minimum child count.
    """

    allowed: bool
    kind: str | None = None
    min: int | None = None

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
        return cls(allowed=allowed, kind=kind, min=minimum)

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
        return out


class ComponentDef(Protocol):
    """Read-only structural view of a component definition."""

    @property
    def name(self) -> str:
        """Component type name (e.g. ``FilledButton``).

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


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """Concrete component definition (implements :class:`ComponentDef`).

    Attributes:
        name: Component type name.
        category: Registry category.
        stability: Stability tag.
        props: Declared props by wire name.
        children: Child-node rules.
    """

    name: str
    category: str
    stability: str
    props: Mapping[str, PropDef]
    children: ChildrenRule

    def __post_init__(self) -> None:
        object.__setattr__(self, "props", MappingProxyType(dict(self.props)))

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
        return cls(
            name=name,
            category=category,
            stability=stability,
            props=props,
            children=ChildrenRule.from_mapping(raw_children, where=f"{name}.children"),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the ``components.json`` component shape.

        Returns:
            A JSON-ready dict.
        """
        return {
            "category": self.category,
            "stability": self.stability,
            "props": {name: prop.to_mapping() for name, prop in self.props.items()},
            "children": self.children.to_mapping(),
        }


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


@dataclass(frozen=True, slots=True)
class Registry(AbstractComponentRegistry):
    """Frozen, in-memory view of the component registry.

    Attributes:
        schema_version: The IR contract version (``schemaVersion``).
        min_library_version: The minimum library version required.
        components: Component definitions by name.
        actions: Action definitions by id.
        modifiers: Ordered modifier operation definitions by wire name.
    """

    schema_version: str
    min_library_version: str
    components: Mapping[str, ComponentSpec]
    actions: Mapping[str, ActionDef]
    modifiers: Mapping[str, Mapping[str, PropDef]] = dataclass_field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))
        object.__setattr__(self, "actions", MappingProxyType(dict(self.actions)))
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
        return cls(
            schema_version=schema_version,
            min_library_version=min_library_version,
            components=components,
            actions=actions,
            modifiers=_parse_modifiers(data.get("modifiers", {})),
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
        }
        if self.modifiers:
            result["modifiers"] = {
                name: {"props": {key: prop.to_mapping() for key, prop in props.items()}}
                for name, props in self.modifiers.items()
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
