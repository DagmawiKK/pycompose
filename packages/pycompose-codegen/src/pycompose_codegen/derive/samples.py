"""One sample snapshot per component, built from its types alone.

Each required prop gets a value of its type, each action a declared binding,
each required slot a ``Text``, a scoped component its provider as parent, and
a control with nothing naming it a semantics label. The library's render gate
renders one per catalog component; ``pycompose add`` renders one per component
of an app's own libraries.
"""

from __future__ import annotations

from typing import Any

from pycompose.model.catalog.lock import SCHEMA_VERSION
from pycompose.model.programs.drawing import CANVAS, DRAW, draws
from pycompose.model.programs.layout import LAYOUT, MEASURED
from pycompose.model.programs.refs import lift

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
    if kind == "enum" and "valueType" in spec:
        return _constant(where, spec["valueType"], spec["values"][0], values)
    if kind == "enum":
        return spec["values"][0]
    if kind in {"integer", "number", "int", "float"}:
        integral = kind in {"integer", "int"}
        number: float = (0 if integral else 0.5) if order is None else order
        return min(
            max(number, spec.get("minimum", number)), spec.get("maximum", number)
        )
    return _structured(where, spec, values)


def _structured(where: str, spec: dict[str, Any], values: dict[str, Any]) -> Any:
    """A sample of a type that is more than one literal."""
    kind = spec["type"]
    if kind == "resource":
        return f"@{spec['values'][0]}/preview"
    if kind == "value":
        sample = _family(where, spec["valueType"], values)
        if "minimum" in spec and isinstance(sample, dict):
            # A bounded Dp is bounded on its number, as the wire checks it.
            sample = {
                k: max(v, spec["minimum"])
                if isinstance(v, int | float) and not isinstance(v, bool)
                else v
                for k, v in sample.items()
            }
        return sample
    if kind == "draw":
        return _drawing()
    if kind == "layout":
        return _layout()
    raise ValueError(f"{where}: no sample for a required {kind} prop")


def _drawing() -> dict[str, Any]:
    """A draw program making the pin's first draw call once, every argument set."""
    name, spec = sorted(draws().items())[0]
    literals = {
        "integer": {"integer": 0xFF6750A4},
        "number": {"number": 8.0},
        "boolean": {"boolean": True},
    }
    return {
        "type": "program",
        "params": list(CANVAS),
        "result": DRAW,
        "body": [
            {"call": name, "args": [literals[a["type"]] for a in spec["arguments"]]}
        ],
    }


def _layout() -> dict[str, Any]:
    """A layout program placing every child at the origin, sized to the first."""
    first = [
        {"op": f"child{side}", "args": [{"integer": 0}]} for side in ("Width", "Height")
    ]
    origin = [{"loop": 0}, {"number": 0.0}, {"number": 0.0}]
    return {
        "type": "program",
        "params": list(MEASURED),
        "result": LAYOUT,
        "body": [
            {"repeat": "children", "body": [{"call": "place", "args": origin}]},
            {"call": "size", "args": first},
        ],
    }


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


def _constant(where: str, family: str, wanted: str, values: dict[str, Any]) -> Any:
    """The tagged constant of ``family`` an app names ``wanted``."""
    for constructor, entry in sorted(values.items()):
        if not isinstance(entry, dict) or entry.get("family") != family:
            continue
        names = entry.get("parameters", {}).get("name", {}).get("values", [])
        for name in names:
            if wanted in (name, name[:1].lower() + name[1:]):
                return {"type": constructor, "name": name}
    raise ValueError(f"{where}: no constant {wanted!r} in {family}")


def _required(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        name: spec
        for name, spec in entry.get("parameters", {}).items()
        if spec.get("required")
    }


class _Sample:
    """Builds one snapshot, collecting the intents its props name."""

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
            {**self._filler(spec, f"{id}.{slot}", slot), "slot": slot}
            for slot, spec in sorted((entry.get("slots") or {}).items())
            if not spec.get("nullable") and not spec.get("host")
        ]
        if entry["children"].get("allowed"):
            children.append(self._filler(entry["children"], f"{id}.child", name))
        texts = [
            prop
            for prop in props
            if entry["props"][prop]["type"] in {"string", "resource"}
            or entry["props"][prop].get("valueType") == "AnnotatedString"
        ]
        if not children and not texts and "modifier" in entry["props"]:
            # Nothing in the sample names it (a Checkbox, a Slider): its label
            # comes from semantics, as an app's must. An item wears none.
            props["modifier"] = {
                "operations": [{"type": "semantics", "contentDescription": name}]
            }
        node: dict[str, Any] = {"id": id, "type": name, "props": props}
        if children:
            node["children"] = children
        return node

    def _filler(self, channel: dict[str, Any], id: str, text: str) -> dict[str, Any]:
        """A channel's filler: a ``Text``, or a builder's first applied item."""
        if channel.get("kind") != "members":
            return {"id": id, "type": "Text", "props": {"text": text}}
        item = next(
            name
            for name, entry in sorted(self.components.items())
            if entry.get("item") and entry["scope"] in channel["applies"]
        )
        return self.node(item, id)

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
        """The component, inside the parent its scope requires, or beside the
        node whose holder it shares."""
        scope = self.components[name].get("scope")
        if self.components[name].get("shared"):
            return self._sharing(name)
        if scope is not None:
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

    def _sharing(self, name: str) -> dict[str, Any]:
        """The component in a column beside an owner of the holders it shares."""
        child = self.node(name, "preview")
        owners = []
        for native, holder in sorted(self.components[name]["shared"].items()):
            owner = next(
                other
                for other, entry in sorted(self.components.items())
                if (entry.get("state") or {}).get("holder") == holder
                and not entry.get("shared")
            )
            owners.append(self.node(owner, f"owner.{native}"))
            child["props"][native] = f"owner.{native}"
        root = self.node("Column", "page")
        root["children"] = [*owners, child]
        return root

    def _provider(self, scope: str) -> tuple[str, str | None]:
        """The first component providing a scope, and the slot that does, if one."""
        for name, entry in sorted(self.components.items()):
            if "scope" in entry:
                continue
            # A builder's channel applies its scope's items, a supertype's too.
            if scope in _provided(entry["children"]):
                return name, None
            for slot, spec in sorted((entry.get("slots") or {}).items()):
                if scope in _provided(spec):
                    return name, slot
        raise ValueError(f"no component provides {scope}")


def _provided(channel: dict[str, Any]) -> set[str]:
    """The scopes a channel's children may need: its receiver, and what it applies."""
    return {channel.get("provides"), *channel.get("applies", ())} - {None}


def sample(catalog: dict[str, Any], name: str) -> dict[str, Any]:
    """A snapshot composing one component, ready for the validator.

    Args:
        catalog: The catalog lock: its components and value families.
        name: The component to sample.

    Returns:
        The snapshot document.
    """
    builder = _Sample(catalog)
    return _document(builder.scoped(name), builder.bindings)


def modifier_sample(catalog: dict[str, Any], name: str) -> dict[str, Any]:
    """A snapshot of a Box wearing one modifier, its required props filled.

    Args:
        catalog: The catalog lock: its modifiers and value families.
        name: The modifier to sample; one a scope declares is sampled inside
            its parent instead, so is not taken here.

    Returns:
        The snapshot document.
    """
    builder = _Sample(catalog)
    operation: dict[str, Any] = {"type": name}
    for prop, spec in catalog["modifiers"][name]["props"].items():
        if spec["type"] == "actionId" and spec.get("required"):
            operation[prop] = builder._binding(prop, spec)
        elif spec.get("required"):
            operation[prop] = _value(f"{name}.{prop}", spec, builder.values)
    root = {
        "id": "preview",
        "type": "Box",
        "props": {"modifier": {"operations": [operation]}},
        "children": [{"id": "preview.child", "type": "Text", "props": {"text": name}}],
    }
    return _document(root, builder.bindings)


def _document(root: dict[str, Any], intents: dict[str, Any]) -> dict[str, Any]:
    """The snapshot holding ``root``, its programs named by content as emission does."""
    programs: dict[str, object] = {}
    lifted = lift(root, programs.__setitem__)
    metadata: dict[str, Any] = {"intents": intents}
    if programs:
        metadata["programs"] = dict(sorted(programs.items()))
    return {
        "version": "0.1.0",
        "schemaVersion": SCHEMA_VERSION,
        "root": lifted,
        "metadata": metadata,
    }
