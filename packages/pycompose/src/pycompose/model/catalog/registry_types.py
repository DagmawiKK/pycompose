"""Runtime registry types mirroring ``schema/catalog.lock.json``.

The registry is the single source of truth for which components and
actions exist and what shape their props/payloads take. These frozen,
stdlib-only types are the runtime view consumed by the emitter;
:meth:`Registry.from_mapping` and :meth:`Registry.to_mapping` round-trip
the JSON so the file and the types cannot silently diverge.

The prop-type vocabulary is validated by the codegen tool (``tools/schema``)
and the generated validators; here ``type`` is treated as an opaque string.

The vocabulary, leaf rules, prop definitions and component definitions
live in sibling modules (``registry_vocabulary``, ``registry_elements``,
``registry_props``, ``registry_component``) whose import chain is
downward-only; this module re-exports their surface so established imports
keep resolving at one path, and adds :class:`ActionDef` and the
:class:`Registry` aggregate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from types import MappingProxyType
from typing import cast

from pycompose.errors import ComponentRegistryError
from pycompose.model.catalog.registry_component import ComponentDef, ComponentSpec
from pycompose.model.catalog.registry_elements import (
    ChildrenRule,
    ContentSlot,
    ProviderDef,
    SlotRule,
)
from pycompose.model.catalog.registry_modifiers import (
    derived_modifiers,
    modifiers_mapping,
    parse_modifiers,
)
from pycompose.model.catalog.registry_props import InteractionRule, PropDef
from pycompose.model.catalog.registry_state import StateRule
from pycompose.model.catalog.registry_transient import TransientRule
from pycompose.model.catalog.registry_vocabulary import (
    ADAPTERS,
    CONSUMERS,
    DECODED_TYPES,
    DECODERS,
    INTERACTION_KINDS,
    OWNERS,
    SLOT_KINDS,
    STATE_KINDS,
    TRANSIENT_KINDS,
    WRAPPERS,
)

__all__ = [
    "ADAPTERS",
    "AbstractComponentRegistry",
    "ActionDef",
    "ChildrenRule",
    "ComponentDef",
    "ComponentSpec",
    "CONSUMERS",
    "ContentSlot",
    "DECODED_TYPES",
    "DECODERS",
    "INTERACTION_KINDS",
    "InteractionRule",
    "OWNERS",
    "PropDef",
    "ProviderDef",
    "Registry",
    "SLOT_KINDS",
    "STATE_KINDS",
    "SlotRule",
    "StateRule",
    "TRANSIENT_KINDS",
    "TransientRule",
    "WRAPPERS",
]


@dataclass(frozen=True, slots=True)
class ActionDef:
    """An action definition: its id and typed payload fields.

    Attributes:
        action_id: The ``actionId`` the host sends.
        payload: Payload fields by name.
        summary: What it does in one sentence, for generated documentation.
        detail: More about it, for generated documentation.
    """

    action_id: str
    payload: Mapping[str, PropDef]
    summary: str | None = None
    detail: str | None = None

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
        return cls(
            action_id=action_id,
            payload=payload,
            summary=cast("str | None", data.get("summary")),
            detail=cast("str | None", data.get("detail")),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the catalog lock action shape.

        Returns:
            A JSON-ready dict.
        """
        documented = {"summary": self.summary, "detail": self.detail}
        return {
            **{key: value for key, value in documented.items() if value is not None},
            "payload": {
                name: field.to_mapping() for name, field in self.payload.items()
            },
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


def _named_objects(
    data: Mapping[str, object], section: str
) -> dict[str, Mapping[str, object]]:
    """Parse an optional section of named objects the runtime carries but does not read.

    Args:
        data: The parsed registry JSON.
        section: The section's key, e.g. ``valueTypes`` or ``holders``.

    Returns:
        Each entry's object, by name; empty when the section is absent.

    Raises:
        ComponentRegistryError: If the section is present but malformed.
    """
    value = data.get(section)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ComponentRegistryError(f"{section!r} must be an object")
    entries: dict[str, Mapping[str, object]] = {}
    for name, spec in value.items():
        if not isinstance(spec, Mapping):
            raise ComponentRegistryError(f"{section}.{name} must be an object")
        entries[name] = dict(spec)
    return entries


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
        derived_modifiers: Per modifier derived from the pin, the version it
            entered at and the scopes declaring it (``weight`` on rows and
            columns). Codegen-only.
        supported_schema_versions: Explicit compatible wire versions, when declared.
        value_types: The declared encodings for structured values, by name.
            Material3 carries thousands of parameters typed ``Color``, ``Dp`` or
            ``Shape``; these say how each family crosses as JSON, so a new
            Compose type costs one entry rather than a new mechanism.
        holders: Each native state holder's derived drive table, by class.
            Host codegen reads it; the Python runtime only carries it.
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
    derived_modifiers: Mapping[str, Mapping[str, object]] = dataclass_field(
        default_factory=dict
    )
    supported_schema_versions: tuple[str, ...] = ()
    value_types: Mapping[str, Mapping[str, object]] = dataclass_field(
        default_factory=dict
    )
    holders: Mapping[str, Mapping[str, object]] = dataclass_field(default_factory=dict)
    _own: dict[str, ComponentSpec] = dataclass_field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _added: set[str] = dataclass_field(
        default_factory=set, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "value_types", MappingProxyType(dict(self.value_types))
        )
        object.__setattr__(self, "holders", MappingProxyType(dict(self.holders)))
        object.__setattr__(
            self, "supported_schema_versions", tuple(self.supported_schema_versions)
        )
        object.__setattr__(self, "_own", dict(self.components))
        object.__setattr__(self, "components", MappingProxyType(self._own))
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

    def extend(self, components: Mapping[str, Mapping[str, object]]) -> None:
        """Add the components an app's own libraries bring.

        An app's generated package registers its lock slice on import, before
        anything is composed; a debug reload registers it again, replacing what
        it added. The catalog's own names never change.

        Args:
            components: Component entries by name, as the lock carries them.

        Raises:
            ComponentRegistryError: If a name is one of the catalog's own.
        """
        for name, body in components.items():
            if name in self._own and name not in self._added:
                raise ComponentRegistryError(f"component {name!r} is the catalog's own")
            self._own[name] = ComponentSpec.from_mapping(name, body)
            self._added.add(name)

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> Registry:
        """Parse a :class:`Registry` from raw the catalog lock data.

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
            modifiers=parse_modifiers(data.get("modifiers", {})),
            derived_modifiers=derived_modifiers(data.get("modifiers", {})),
            supported_schema_versions=tuple(supported),
            value_types=_named_objects(data, "valueTypes"),
            holders=_named_objects(data, "holders"),
        )

    def to_mapping(self) -> dict[str, object]:
        """Render back to the catalog lock shape.

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
            result["modifiers"] = modifiers_mapping(
                self.modifiers, self.derived_modifiers
            )
        if self.supported_schema_versions:
            result["supportedSchemaVersions"] = list(self.supported_schema_versions)
        for section, entries in (
            ("valueTypes", self.value_types),
            ("holders", self.holders),
        ):
            if entries:
                result[section] = {name: dict(spec) for name, spec in entries.items()}
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
