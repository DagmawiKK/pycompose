"""Write one sample snapshot per catalog component for the render gate.

Every component the lock exposes is composed once on the JVM before an app
can reach it (plan 31 §10). The sample is built from the component's types
alone: each required prop gets a value of its type, each action a declared
binding, each required slot a ``Text``, and a scoped component its provider
as parent. Python's validator accepts every sample before it is written; the
host's ``PreviewRenderTest`` renders each one and fails on any report.

    python tools/previews.py            # regenerate
    python tools/previews.py --check    # fail if the committed samples are stale
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pycompose.cli.validate import validate_file
from pycompose.ir.generated_validators import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "schema/catalog.lock.json"
PREVIEWS = ROOT / "android/host/src/test/resources/previews"

VALUES: dict[str, Any] = {
    "AnnotatedString": {"type": "AnnotatedString", "text": "Preview"},
    "ImageVector": {"type": "materialIcon", "name": "Filled.Add"},
    "Range": {"type": "Range", "start": 0.0, "end": 1.0},
    "Shape": {"type": "RoundedCornerShape", "size": {"type": "Dp", "value": 8}},
    "ToggleableState": {"type": "ToggleableState", "name": "On"},
}
"""A sample for each value family a required prop takes; the validator checks them."""

SEARCH_OWNERS: dict[str, tuple[str, str]] = {
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


def _value(name: str, prop: str, spec: dict[str, Any]) -> Any:
    kind = spec["type"]
    if kind in SCALARS:
        return SCALARS[kind]
    if kind == "enum":
        return spec["values"][0]
    if kind in {"integer", "number"}:
        # The smallest ordinary value the range allows: an index of 0, not the
        # most negative Int the wire type can carry.
        sample = 0 if kind == "integer" else 0.5
        return min(
            max(sample, spec.get("minimum", sample)), spec.get("maximum", sample)
        )
    if kind == "resource":
        return f"@{spec['values'][0]}/preview"
    if kind == "value" and spec.get("valueType") in VALUES:
        return VALUES[spec["valueType"]]
    raise ValueError(f"{name}.{prop}: no sample for a required {kind} prop")


class _Sample:
    """Builds one snapshot, collecting the action bindings its props name."""

    def __init__(self, components: dict[str, Any]) -> None:
        self.components = components
        self.bindings: dict[str, Any] = {}

    def node(self, name: str, id: str) -> dict[str, Any]:
        entry = self.components[name]
        props: dict[str, Any] = {}
        for prop, spec in entry["props"].items():
            if spec["type"] == "actionId" and spec.get("required"):
                props[prop] = self._binding(prop, spec)
            elif spec.get("required"):
                props[prop] = _value(name, prop, spec)
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
        node: dict[str, Any] = {"id": id, "type": name, "props": props}
        if children:
            node["children"] = children
        return node

    def _binding(self, prop: str, spec: dict[str, Any]) -> str:
        binding = f"app.preview.{prop}"
        self.bindings[binding] = {
            "bound": {},
            "handlerId": f"preview.{prop}",
            "payload": {
                field["name"]: {"required": True, "type": field["type"]}
                for field in spec.get("payload", [])
            },
        }
        return binding

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


def documents() -> dict[str, dict[str, Any]]:
    """Return one valid sample snapshot per component.

    Returns:
        Snapshots by component name.

    Raises:
        ValueError: A sample the validator refuses, naming the component.
    """
    components = json.loads(LOCK.read_text(encoding="utf-8"))["components"]
    samples = {}
    for name in sorted(components):
        sample = _Sample(components)
        root = sample.scoped(name)
        document = {
            "version": "0.1.0",
            "schemaVersion": SCHEMA_VERSION,
            "root": root,
            "metadata": {"actionBindings": sample.bindings},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            path.write_text(json.dumps(document))
            try:
                validate_file(path)
            except Exception as exc:
                raise ValueError(f"{name}: sample refused: {exc}") from exc
        samples[name] = document
    return samples


def render() -> dict[str, str]:
    """Return every sample file's text, plus the index the host test reads.

    Returns:
        File names to contents.
    """
    samples = documents()
    files = {
        f"{name}.json": json.dumps(document, indent=1, sort_keys=True) + "\n"
        for name, document in samples.items()
    }
    files["index.txt"] = "".join(f"{name}\n" for name in samples)
    return files


def main() -> int:
    """Write or check the samples.

    Returns:
        A process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    files = render()
    present = {path.name for path in PREVIEWS.glob("*")} if PREVIEWS.is_dir() else set()
    stale = sorted(
        name
        for name, text in files.items()
        if name not in present or (PREVIEWS / name).read_text() != text
    ) + sorted(present - set(files))
    if check:
        if stale:
            print(f"previews.py: stale samples: {', '.join(stale)}", file=sys.stderr)
            return 1
        return 0
    PREVIEWS.mkdir(parents=True, exist_ok=True)
    for name in present - set(files):
        (PREVIEWS / name).unlink()
    for name, text in files.items():
        (PREVIEWS / name).write_text(text)
    print(f"previews.py: wrote {len(files) - 1} samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
