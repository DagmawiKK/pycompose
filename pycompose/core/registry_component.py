"""Component-level types of the component registry.

:class:`ComponentSpec` is the concrete frozen definition a registry entry
round-trips to, and :class:`ComponentDef` its read-only structural view.
The helper parsers here (:func:`_adapter`, :func:`_wrapper`,
:func:`_opt_in`, :func:`_reshaped`) refuse unknown component-level kinds
rather than ignoring them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from types import MappingProxyType
from typing import Protocol, cast

from pycompose.core.registry_elements import ChildrenRule, SlotRule
from pycompose.core.registry_props import InteractionRule, PropDef, StateRule
from pycompose.core.registry_transient import TransientRule
from pycompose.core.registry_vocabulary import ADAPTERS, SCOPES, WRAPPERS
from pycompose.errors import ComponentRegistryError


class ComponentDef(Protocol):
    """Read-only structural view of a component definition."""

    @property
    def name(self) -> str:
        """Component type name (e.g. ``Button``).

        Returns:
            The component name.
        """

    @property
    def category(self) -> str:
        """Registry category (e.g. ``buttons``).

        Returns:
            The category name.
        """

    @property
    def stability(self) -> str:
        """Stability tag (``stable``/``beta``/``experimental``).

        Returns:
            The stability tag.
        """

    @property
    def props(self) -> Mapping[str, PropDef]:
        """Declared props by wire name.

        Returns:
            The props mapping.
        """

    @property
    def children(self) -> ChildrenRule:
        """Child-node rules.

        Returns:
            The children rule.
        """

    @property
    def slots(self) -> Mapping[str, SlotRule]:
        """Named slots by wire name.

        Returns:
            The slot rules.
        """


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


def _opt_in(name: str, value: object) -> tuple[str, ...]:
    """Parse a component's declared opt-in markers.

    Args:
        name: The component's registry key, for the error message.
        value: The raw ``optIn`` field.

    Returns:
        The marker names, in declaration order.

    Raises:
        ComponentRegistryError: If the field is present but malformed.
    """
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ComponentRegistryError(
            f"component {name!r}: 'optIn' must be a string list"
        )
    return tuple(value)


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


def _transient(name: str, value: object) -> TransientRule | None:
    """Parse a component's declared transient request.

    Args:
        name: The component's registry key, for the error message.
        value: The raw ``transient`` field.

    Returns:
        The parsed rule, or None when the component declares none.

    Raises:
        ComponentRegistryError: If the field is present but malformed.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ComponentRegistryError(
            f"component {name!r}: 'transient' must be an object"
        )
    return TransientRule.from_mapping(value, where=f"{name}.transient")


def _source(name: str, value: object) -> Mapping[str, str] | None:
    """Parse a component's recorded pinned identity.

    Args:
        name: The component's registry key, for the error message.
        value: The raw ``source`` field.

    Returns:
        The recorded identity, or None when the component claims none.

    Raises:
        ComponentRegistryError: If the field is present but malformed.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise ComponentRegistryError(
            f"component {name!r}: 'source' must be an object of strings"
        )
    return MappingProxyType(dict(value))


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
        state: The host-owned state holder this component accepts, if any.
            Codegen-only: it says which native parameter the renderer fills,
            which prop carries Python's desired state, and which prop reports
            settled changes.
        transient: The host-fulfilled transient request this component
            accepts, if any. Codegen-only: it says which native parameter the
            renderer fills, which prop carries the serial the host compares,
            and which occurrence reports the fulfilled serial back.
        opt_in: Opt-in markers the pinned declaration requires, if any.
            Codegen-only: the generated adapter file declares each one it needs.
        package: The Kotlin package the pinned composable lives in, so a
            generated adapter imports the qualified name instead of a generator
            keeping its own list of where every component lives.
        scope: The composition scope the pinned declaration extends, if any.
            Codegen-only: the adapter registers through the matching scoped
            method, and only a parent that provides the scope can compose it.
        source: The exact pinned overload the generated call binds, as the
            binding compiler resolves it: artifact, owner, name, JVM name and
            JVM descriptor. Absent when the adapter is hand-written and
            legitimately spans a family of overloads.
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
    state: StateRule | None = None
    transient: TransientRule | None = None
    opt_in: tuple[str, ...] = ()
    package: str | None = None
    scope: str | None = None
    source: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "props", MappingProxyType(dict(self.props)))
        object.__setattr__(self, "slots", MappingProxyType(dict(self.slots)))
        if self.source is not None:
            object.__setattr__(self, "source", MappingProxyType(dict(self.source)))
        if self.since is not None and (
            not isinstance(self.since, str) or not self.since
        ):
            raise ComponentRegistryError("since must be a non-empty schema version")
        if self.package is not None and (
            not isinstance(self.package, str) or not self.package
        ):
            raise ComponentRegistryError("package must be a non-empty dotted name")
        if self.scope is not None and self.scope not in SCOPES:
            raise ComponentRegistryError(f"scope must be one of {', '.join(SCOPES)}")

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
        package = data.get("package")
        if package is not None and (not isinstance(package, str) or not package):
            raise ComponentRegistryError(
                f"component {name!r}: 'package' must be a non-empty string"
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
        raw_state = data.get("state")
        if raw_state is not None and not isinstance(raw_state, Mapping):
            raise ComponentRegistryError(
                f"component {name!r}: 'state' must be an object"
            )
        state = (
            StateRule.from_mapping(raw_state, where=f"{name}.state")
            if isinstance(raw_state, Mapping)
            else None
        )
        raw_transient = data.get("transient")
        transient = _transient(name, raw_transient)
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
            state=state,
            transient=transient,
            opt_in=_opt_in(name, data.get("optIn")),
            package=package,
            scope=cast("str | None", data.get("scope")),
            source=_source(name, data.get("source")),
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
        if self.package is not None:
            result["package"] = self.package
        if self.slots:
            result["slots"] = {
                name: rule.to_mapping() for name, rule in self.slots.items()
            }
        if self.interaction is not None:
            result["interaction"] = self.interaction.to_mapping()
        if self.state is not None:
            result["state"] = self.state.to_mapping()
        if self.transient is not None:
            result["transient"] = self.transient.to_mapping()
        if self.since is not None:
            result["since"] = self.since
        if self.reshaped:
            result["reshaped"] = list(self.reshaped)
        if self.adapter != "generated":
            result["adapter"] = self.adapter
        if self.opt_in:
            result["optIn"] = list(self.opt_in)
        if self.wrapper is not None:
            result["wrapper"] = self.wrapper
        if self.scope is not None:
            result["scope"] = self.scope
        if self.source is not None:
            result["source"] = dict(self.source)
        return result
