"""Write one sample snapshot per catalog component for the render gate.

Every component the lock exposes is composed once on the JVM before an app
can reach it. The sample is built from the component's types
alone (``pycompose_codegen.derive.samples``), and Python's validator accepts every
sample before it is written.

Every prop the pin can animate is bound too: one pair of snapshots per
``(component, prop)``, the second with a moved target, so the host's binding
path is rendered for each rather than assumed.

The samples are output of the lock, so they are written into the build
directory, never committed: the host's ``PreviewRenderTest`` and
``BoundRenderTest`` run this tool themselves and render each one.

The same samples become one ``@Preview`` per component in the host's debug
source set, so Android Studio shows the whole catalog; that source is
committed, because the debug build compiles it.

    python tools/previews.py                  # samples and the @Preview catalog
    python tools/previews.py --out DIR        # only the samples, into DIR
    python tools/previews.py --check          # fail if the catalog is stale
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pycompose_cli.commands.validate import validate_file
from pycompose_codegen.derive.bound_samples import binding_sample
from pycompose_codegen.derive.samples import modifier_sample, sample

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "schema/catalog.lock.json"
PREVIEWS = ROOT / "android/host/build/previews"
"""Where the samples go by default: the host's build directory, not git."""
CATALOG = ROOT / "android/host/src/debug/kotlin/com/pycompose/host/GeneratedPreviews.kt"
"""One ``@Preview`` per component: Android Studio's catalog of the samples."""


def _validated(name: str, document: dict[str, Any]) -> dict[str, Any]:
    """The sample, once Python's validator has accepted it.

    Args:
        name: What the sample composes, for the refusal.
        document: The sample snapshot.

    Returns:
        The same document.

    Raises:
        ValueError: A sample the validator refuses, naming what it samples.
    """
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "snapshot.json"
        path.write_text(json.dumps(document))
        try:
            validate_file(path)
        except Exception as exc:
            raise ValueError(f"{name}: sample refused: {exc}") from exc
    return document


def documents() -> dict[str, dict[str, Any]]:
    """Return one valid sample snapshot per component.

    Returns:
        Snapshots by component name.
    """
    catalog = json.loads(LOCK.read_text(encoding="utf-8"))
    return {
        name: _validated(name, sample(catalog, name))
        for name in sorted(catalog["components"])
    }


def modifier_documents() -> dict[str, dict[str, Any]]:
    """Return one valid sample snapshot per modifier any node may wear.

    Returns:
        Snapshots by ``Modifier.<name>``.
    """
    catalog = json.loads(LOCK.read_text(encoding="utf-8"))
    return {
        f"Modifier.{name}": _validated(name, modifier_sample(catalog, name))
        for name, entry in sorted(catalog["modifiers"].items())
        if "scoped" not in entry
    }


def binding_documents() -> dict[str, dict[str, Any]]:
    """Return two frames of one bound sample per bindable ``(component, prop)``.

    Each pair is rendered twice: at the target the catalog derives, and at a
    moved one, so the host travels between them rather than only reading.

    Returns:
        Two snapshots per pair, by ``Component.prop``.
    """
    catalog = json.loads(LOCK.read_text(encoding="utf-8"))
    pairs = [
        (name, prop)
        for name, entry in sorted(catalog["components"].items())
        for prop, spec in entry["props"].items()
        if "animation" in spec
    ]
    return {
        f"{name}.{prop}": {
            "first": _validated(f"{name}.{prop}", binding_sample(catalog, name, prop)),
            "then": _validated(
                f"{name}.{prop}", binding_sample(catalog, name, prop, moved=True)
            ),
        }
        for name, prop in pairs
    }


def binding_files(bindings: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Return every bound sample's file, plus the index the host test reads.

    Args:
        bindings: Two frames per pair, by ``Component.prop``.

    Returns:
        File names to contents.
    """
    files = {
        f"binding-{pair}.json": json.dumps(frames, indent=1, sort_keys=True) + "\n"
        for pair, frames in bindings.items()
    }
    files["bindings.txt"] = "".join(f"{pair}\n" for pair in bindings)
    return files


def render(samples: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Return every sample file's text, plus the index the host test reads.

    Args:
        samples: Snapshots by component name.

    Returns:
        File names to contents.
    """
    files = {
        f"{name}.json": json.dumps(document, indent=1, sort_keys=True) + "\n"
        for name, document in samples.items()
    }
    files["index.txt"] = "".join(f"{name}\n" for name in samples)
    return files


def catalog(samples: dict[str, dict[str, Any]]) -> str:
    """Render the ``@Preview`` catalog: each sample composed by the real renderer.

    Args:
        samples: Snapshots by component name.

    Returns:
        The Kotlin source.
    """
    lines = [
        "// GENERATED by tools/previews.py -- DO NOT EDIT.",
        "// One preview per catalog component, from the render gate's samples.",
        "package com.pycompose.host",
        "",
        "import androidx.compose.runtime.Composable",
        "import androidx.compose.runtime.remember",
        "import androidx.compose.ui.tooling.preview.Preview",
        "import com.pycompose.host.ui.BuiltinComponents",
        "import com.pycompose.host.ui.PyComposeTheme",
        "import com.pycompose.ir.IrParser",
        "import com.pycompose.renderer.ActionDispatcher",
        "import com.pycompose.renderer.Renderer",
        "",
        "@Composable",
        "private fun Sample(source: String) {",
        "    val ir = remember(source) { IrParser().parse(source).getOrThrow() }",
        "    val registry = remember { BuiltinComponents.registry() }",
        "    val renderer = remember { Renderer(registry, ActionDispatcher {}) }",
        "    PyComposeTheme { renderer.Render(ir) }",
        "}",
    ]
    for name, document in samples.items():
        source = json.dumps(document, sort_keys=True).replace("$", "${'$'}")
        lines += [
            "",
            f'@Preview(name = "{name}", showBackground = true)',
            "@Composable",
            f"private fun {name}Preview() {{",
            f'    Sample("""{source}""")',
            "}",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    """Write the samples and the catalog, or check the catalog.

    Returns:
        A process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    samples = documents()
    preview = catalog(samples)
    if args.check:
        if not CATALOG.is_file() or CATALOG.read_text() != preview:
            print(f"previews.py: stale {CATALOG.relative_to(ROOT)}", file=sys.stderr)
            return 1
        return 0
    out = args.out or PREVIEWS
    if out.is_dir():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    # Modifiers are rendered by the gate too, but not listed as previews.
    for name, text in render({**samples, **modifier_documents()}).items():
        (out / name).write_text(text)
    bindings = binding_files(binding_documents())
    for name, text in bindings.items():
        (out / name).write_text(text)
    if args.out is None:
        # A test run asks for samples only; it never rewrites a source file.
        CATALOG.parent.mkdir(parents=True, exist_ok=True)
        CATALOG.write_text(preview)
    print(
        f"previews.py: wrote {len(samples)} samples"
        f" and {len(bindings) - 1} bound pairs to {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
