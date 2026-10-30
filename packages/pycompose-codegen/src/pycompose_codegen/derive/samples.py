"""One sample snapshot per component, built from its types alone.

Each required prop gets a value of its type, each action a declared binding,
each required slot a ``Text``, a scoped component its provider as parent, and
a control with nothing naming it a semantics label. The library's render gate
renders one per catalog component; ``pycompose add`` renders one per component
of an app's own libraries.
"""

from __future__ import annotations

from typing import Any

from pycompose.contract.catalog import SCHEMA_VERSION

SEARCH_OWNERS: dict[str, tuple[str, str | None]] = {
    "ExpandedDockedSearchBar": ("StatefulSearchBar", "expandedBar"),
    "ExpandedFullScreenSearchBar": ("StatefulSearchBar", "expandedBar"),
    "SearchBarStateInputField": ("StatefulSearchBar", "inputField"),
}
"""Components whose adapter shares state with an owner, and the owner's slot.

The search surfaces render one editing projection their StatefulSearchBar
owns (ADR-0016's search family); the lock has no field for that, so the
samples name it here, mirroring StatefulSearchAdapters.kt.
"""

SCALARS: dict[str, Any] = {
    "string": "Preview",
    "boolean": True,
    "color": "#6750A4",
    "dp": 8,
    "durationMs": 300,
}


def _value(
    where: str, spec: dict[str, Any], values: dict[str, Any], order: int | None = None
) -> Any:
    """A valid value of a prop or parameter's type, derived from the catalog.

    A prop's number is the smallest ordinary one: an index of 0, a fraction of
    0.5. Inside a value, ``order`` is the parameter's place: the n-th number is
    n, so a range or an offset is never degenerate.
    """
    kind = spec["type"]
    if kind in SCALARS:
        return spec["values"][0] if "values" in spec else SCALARS[kind]
    if kind == "enum":
        return spec["values"][0]
    if kind in {"integer", "number", "int", "float"}:
        integral = kind in {"integer", "int"}
        number: float = (0 if integral else 0.5) if order is None else order
        return min(
            max(number, spec.get("minimum", number)), spec.get("maximum", number)
        )
    if kind == "resource":
        return f"@{spec['values'][0]}/preview"
    if kind == "value":
        return _family(where, spec["valueType"], values)
    raise ValueError(f"{where}: no sample for a required {kind} prop")


def _family(where: str, family: str, values: dict[str, Any], depth: int = 0) -> Any:
    """The simplest entry of a value family, its required parameters filled."""
    if depth > 4:
        raise ValueError(f"{where}: value family {family} nests too deeply")
    entries = sorted(
        (
            (name, entry)
            for name, entry in values.items()
            if isinstance(entry, dict) and family in {name, entry.get("family")}
        ),
        key=lambda item: (len(_required(item[1])), item[0]),
    )
    for name, entry in entries:
        try:
            return {
                "type": name,
                **{
                    parameter: _value(f"{where}.{parameter}", spec, values, order)
                    for order, (parameter, spec) in enumerate(_required(entry).items())
                },
            }
        except ValueError:
            continue
    raise ValueError(f"{where}: no sample for value family {family}")


def _required(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        name: spec
        for name, spec in entry.get("parameters", {}).items()
        if spec.get("required")
    }


class _Sample:
    """Builds one snapshot, collecting the action bindings its props name."""

    def __init__(self, catalog: dict[str, Any]) -> None:
        self.components = catalog["components"]
        self.values = catalog.get("valueTypes", {})
        self.bindings: dict[str, Any] = {}

    def node(self, name: str, id: str) -> dict[str, Any]:
        entry = self.components[name]
        props: dict[str, Any] = {}
        for prop, spec in entry["props"].items():
            if spec["type"] == "actionId" and spec.get("required"):
                props[prop] = self._binding(prop, spec)
            elif spec.get("required"):
                props[prop] = _value(f"{name}.{prop}", spec, self.values)
        children = [
            {
                "id": f"{id}.{slot}",
                "type": "Text",
                "slot": slot,
                "props": {"text": slot},
            }
            for slot, spec in sorted((entry.get("slots") or {}).items())
            if not spec.get("nullable") and not spec.get("host")
        ]
        if entry["children"].get("allowed"):
            children.append(
                {"id": f"{id}.child", "type": "Text", "props": {"text": name}}
            )
        texts = [
            prop
            for prop in props
            if entry["props"][prop]["type"] in {"string", "resource"}
            or entry["props"][prop].get("valueType") == "AnnotatedString"
        ]
        if not children and not texts:
            # Nothing in the sample names it (a Checkbox, a Slider): its label
            # comes from semantics, as an app's must.
            props["modifier"] = {
                "operations": [{"type": "semantics", "contentDescription": name}]
            }
        node: dict[str, Any] = {"id": id, "type": name, "props": props}
        if children:
            node["children"] = children
        return node

    def _binding(self, prop: str, spec: dict[str, Any]) -> dict[str, Any]:
        handler = f"preview.{prop}"
        self.bindings[handler] = {
            "payload": {
                field["name"]: {"required": True, "type": field["type"]}
                for field in spec.get("payload", [])
            },
        }
        return {"fields": {}, "intent": handler}

    def scoped(self, name: str) -> dict[str, Any]:
        """The component, inside the parent its scope or its owner requires."""
        scope = self.components[name].get("scope")
        if name in SEARCH_OWNERS:
            parent, slot = SEARCH_OWNERS[name]
        elif scope is not None:
            parent, slot = self._provider(scope)
        else:
            return self.node(name, "preview")
        root = self.node(parent, "provider")
        child = self.node(name, "preview")
        children = [c for c in root.get("children", []) if c.get("slot") != slot]
        if slot is not None:
            # The scope is the slot's receiver: the component fills that slot.
            child["slot"] = slot
        root["children"] = [*children, child]
        return root

    def _provider(self, scope: str) -> tuple[str, str | None]:
        """The first component providing a scope, and the slot that does, if one."""
        for name, entry in sorted(self.components.items()):
            if "scope" in entry:
                continue
            if entry["children"].get("provides") == scope:
                return name, None
            for slot, spec in sorted((entry.get("slots") or {}).items()):
                if spec.get("provides") == scope:
                    return name, slot
        raise ValueError(f"no component provides {scope}")


def sample(catalog: dict[str, Any], name: str) -> dict[str, Any]:
    """A snapshot composing one component, ready for the validator.

    Args:
        catalog: The catalog lock: its components and value families.
        name: The component to sample.

    Returns:
        The snapshot document.
    """
    builder = _Sample(catalog)
    root = builder.scoped(name)
    return {
        "version": "0.1.0",
        "schemaVersion": SCHEMA_VERSION,
        "root": root,
        "metadata": {"intents": builder.bindings},
    }
