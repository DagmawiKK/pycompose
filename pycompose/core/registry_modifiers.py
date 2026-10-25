"""The catalog's modifier operations: their props, and the scopes declaring them.

Most operations are approved policy (``padding``, ``semantics``). A modifier a
composition scope declares (``RowScope.weight``) is derived from the pin and
carries the scopes it is declared in; only a child composed inside one of them
can wear it, which the host checks when it applies the operation.
"""

from __future__ import annotations

from collections.abc import Mapping

from pycompose.core.registry_props import PropDef
from pycompose.errors import ComponentRegistryError


def parse_modifiers(raw: object) -> Mapping[str, Mapping[str, PropDef]]:
    """Parse every operation's props.

    Args:
        raw: The catalog's ``modifiers`` section.

    Returns:
        Each operation's props, by wire name.

    Raises:
        ComponentRegistryError: If an operation is malformed.
    """
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


def derived_modifiers(raw: object) -> dict[str, Mapping[str, object]]:
    """What each modifier derived from the pin carries besides its props.

    Args:
        raw: The catalog's ``modifiers`` section, already parsed once.

    Returns:
        Each derived operation's ``since`` and ``scoped`` declarations, by wire
        name.

    Raises:
        ComponentRegistryError: If a declaration does not name its scope.
    """
    derived: dict[str, Mapping[str, object]] = {}
    for name, body in (raw if isinstance(raw, Mapping) else {}).items():
        if not isinstance(body, Mapping) or "scoped" not in body:
            continue
        scoped = body["scoped"]
        if not isinstance(scoped, list) or not all(
            isinstance(item, Mapping) and isinstance(item.get("scope"), str)
            for item in scoped
        ):
            raise ComponentRegistryError("'scoped' must name scopes", modifier=name)
        derived[name] = {key: value for key, value in body.items() if key != "props"}
    return derived


def modifiers_mapping(
    modifiers: Mapping[str, Mapping[str, PropDef]],
    derived: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Render the section back, as the catalog lock carries it.

    Args:
        modifiers: Each operation's props.
        derived: The derived operations' ``since`` and declarations.

    Returns:
        The ``modifiers`` section.
    """
    return {
        name: {
            "props": {key: prop.to_mapping() for key, prop in props.items()},
            **derived.get(name, {}),
        }
        for name, props in modifiers.items()
    }
