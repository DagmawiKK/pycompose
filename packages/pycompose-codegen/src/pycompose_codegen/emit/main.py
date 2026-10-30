#!/usr/bin/env python3
"""SSOT codegen: derive ``schema/ir.schema.json`` and Python validator tables.

Run from anywhere inside the repo:

    python tools/schema/gen.py          # regenerate derived artifacts
    python tools/schema/gen.py --check  # fail on drift (CI / pre-commit)

Pure stdlib, fully deterministic: no timestamps, no environment reads, keys
sorted. Generated files are committed and must never be hand-edited.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pycompose_codegen.checkout import PACKAGE, ROOT
from pycompose_codegen.emit.rules import (
    PACKAGED_CATALOG,
    SCHEMA_PATH,
    load_registry,
)

# Public aliases the CLI, packaging and tests already import from this module.
__all__ = [
    "PACKAGED_CATALOG",
    "SCHEMA_PATH",
    "build_app",
    "framework_artifacts",
    "main",
]


IR_SCHEMA_PATH = ROOT / "schema" / "ir.schema.json"
PAYLOADS_PATH = PACKAGE / "bridge" / "generated_payloads.py"
KOTLIN_ADAPTERS_PATH = (
    ROOT / "android/host/src/main/kotlin/com/pycompose/host/ui/GeneratedAdapters.kt"
)

KOTLIN_MODELS_PATH = (
    ROOT / "android/ir/src/main/kotlin/com/pycompose/ir/generated/UiModels.kt"
)
KOTLIN_REGISTRY_PATH = (
    ROOT / "android/ir/src/main/kotlin/com/pycompose/ir/generated/IrContract.kt"
)
KOTLIN_VALUES_RELATIVE = Path(
    "android/renderer/src/main/kotlin/com/pycompose/renderer/generated/ValueResolver.kt"
)
KOTLIN_DRIVES_RELATIVE = KOTLIN_VALUES_RELATIVE.with_name("HolderDrives.kt")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def build_app(
    python_root: Path,
    *,
    android_root: Path | None = None,
    check: bool = False,
    app_lock: Path | None = None,
    kotlin: bool = True,
) -> int:
    """Generate an app's component slice, or verify it (ADR-0014).

    The two roots are separate because a scaffolded project keeps them apart:
    ``pycompose init`` writes Python under ``app/`` and the Gradle project at
    the repository root, so the Kotlin slice belongs beside ``android/`` while
    the generated package belongs beside the app's own sources. The notes
    example puts both in one directory, which is why a single root looked
    sufficient until it was not.

    The Kotlin slice lands in the project's ``.pycompose/generated`` tree,
    bound to the scaffold modules by their build files, and carries the app's
    referenced components plus the framework floor every host compiles against
    (``app_slice.FLOOR_COMPONENTS``).

    Args:
        python_root: Where the app's Python lives; receives the generated package.
        android_root: Where the Kotlin slice goes; defaults to ``python_root``.
        check: Report drift instead of writing.
        app_lock: The app's lock slice (``compose.lock.json``), whose components
            join the library's; None or a missing file adds none.
        kotlin: Also write the Kotlin half. The dev server writes only the
            Python package: the dev client carries the whole catalog.

    Returns:
        Process exit code: 0 clean, 1 on drift or an unresolvable app.
    """
    from pycompose_codegen.emit.app_slice import (
        _ADAPTERS_RELATIVE,
        _IR_RELATIVE,
        _VALUES_RELATIVE,
        APP_PACKAGE,
        FLOOR_COMPONENTS,
        AppCodegenError,
        app_components,
        discover,
        discover_values,
        load_catalog,
        slice_registry,
        with_app_lock,
    )
    from pycompose_codegen.emit.emit_kotlin import (
        render_generated_adapters,
        render_kotlin_models,
        render_kotlin_registry,
    )
    from pycompose_codegen.emit.emit_modules import render_python_exports
    from pycompose_codegen.emit.emit_python import render_python_components
    from pycompose_codegen.emit.holders_kotlin import render_holder_drives
    from pycompose_codegen.emit.modifiers_kotlin import render_modifiers
    from pycompose_codegen.emit.values import render_python
    from pycompose_codegen.emit.values_kotlin import (
        render_models,
        render_native,
    )

    native = python_root if android_root is None else android_root
    for root in (python_root, native) if kotlin else (python_root,):
        if not root.is_dir():
            print(f"gen.py: not a directory: {root}", file=sys.stderr)
            return 1
    try:
        own = app_components(app_lock)
        registry = with_app_lock(load_catalog(SCHEMA_PATH), own)
        # The app's own libraries are always built: it asked for them by name.
        used = discover(python_root, registry) | set(own)
    except AppCodegenError as exc:
        print(f"gen.py: {exc}", file=sys.stderr)
        return 1
    problem = _slicing_problem(registry, used, python_root)
    if problem:
        print(f"gen.py: {problem}", file=sys.stderr)
        return 1

    sliced = slice_registry(
        registry,
        used | FLOOR_COMPONENTS,
        values=frozenset(discover_values(python_root, registry)),
    )

    package = APP_PACKAGE
    artifacts: dict[Path, str] = {
        python_root / package / "generated_components.py": render_python_components(
            sliced,
            package,
            {
                name: entry
                for name, entry in sliced["components"].items()
                if name in own
            },
        ),
        python_root / package / "__init__.py": render_python_exports(sliced, package),
        python_root / package / "values.py": render_python(sliced),
    }
    kotlin_artifacts = {
        native / _IR_RELATIVE / "UiModels.kt": render_kotlin_models(sliced),
        native / _IR_RELATIVE / "IrContract.kt": render_kotlin_registry(sliced),
        native / _IR_RELATIVE / "ValueModels.kt": render_models(sliced),
        native / _VALUES_RELATIVE: render_native(sliced),
        # The renderer's own holder code calls every drive, used or not: unsliced.
        native / _VALUES_RELATIVE.with_name("HolderDrives.kt"): render_holder_drives(
            registry
        ),
        native / _ADAPTERS_RELATIVE: render_generated_adapters(sliced),
        native / _VALUES_RELATIVE.with_name("GeneratedModifiers.kt"): (
            render_modifiers(sliced)
        ),
    }
    if kotlin:
        artifacts.update(kotlin_artifacts)

    if check:
        drifted = [
            str(artifact)
            for artifact, expected in artifacts.items()
            if _read(artifact) != expected
        ]
        if drifted:
            for artifact in drifted:
                print(f"gen.py: drift detected: {artifact}", file=sys.stderr)
            return 1
        print(f"gen.py: app slice up to date ({len(used)} component(s))")
        return 0

    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    manual = [
        name
        for name in sliced["components"]
        if sliced["components"][name].get("adapter") == "manual"
    ]
    print(
        f"gen.py: {python_root}: {len(sliced['components'])} component(s) generated "
        f"({len(used)} referenced, {len(artifacts)} artifact(s)); "
        + (
            f"hand-written adapters still needed for {', '.join(sorted(manual))}"
            if manual
            else "no hand-written adapters needed"
        )
    )
    return 0


def _slicing_problem(registry: dict[str, Any], used: set[str], app: Path) -> str | None:
    """Explain why an app cannot be sliced, or None when it can.

    Args:
        registry: The parsed catalog.
        used: The component names the app references.
        app: The app's Python root, for the message.

    Returns:
        The problem to report, or None.
    """
    from pycompose_codegen.emit.app_slice import FLOOR_COMPONENTS

    if not used:
        return f"{app} references no components; nothing to generate"
    floorless = FLOOR_COMPONENTS.difference(registry["components"])
    if floorless:
        return (
            "catalog is missing components every host compiles against: "
            + ", ".join(sorted(floorless))
        )
    return None


def framework_artifacts(registry: dict[str, Any]) -> dict[Path, str]:
    """Build every framework artifact one generation emits, without touching disk.

    Args:
        registry: The validated catalog mapping.

    Returns:
        Artifact paths keyed to their full rendered content; the template
        mirror is added by :func:`_mirror_template` on top of this mapping.
    """
    from pycompose_codegen.emit.emit_kotlin import (
        render_generated_adapters,
        render_kotlin_models,
        render_kotlin_registry,
    )
    from pycompose_codegen.emit.emit_modules import (
        libraries,
        render_payloads,
        render_python_exports,
    )
    from pycompose_codegen.emit.emit_python import render_python_components
    from pycompose_codegen.emit.emit_wire import render_ir_schema
    from pycompose_codegen.emit.holders_kotlin import render_holder_drives
    from pycompose_codegen.emit.modifiers_kotlin import render_modifiers
    from pycompose_codegen.emit.scoped_modifiers_python import (
        render_scoped_operations,
    )
    from pycompose_codegen.emit.values import render_python as render_values
    from pycompose_codegen.emit.values_kotlin import (
        render_models,
        render_native,
    )

    artifacts = {
        IR_SCHEMA_PATH: render_ir_schema(registry),
        PAYLOADS_PATH: render_payloads(registry),
        KOTLIN_MODELS_PATH: render_kotlin_models(registry),
        KOTLIN_REGISTRY_PATH: render_kotlin_registry(registry),
        PACKAGE / "values.py": render_values(registry),
        KOTLIN_MODELS_PATH.with_name("ValueModels.kt"): render_models(registry),
        ROOT / KOTLIN_VALUES_RELATIVE: render_native(registry),
    }
    for name, part in libraries(registry).items():
        package = f"pycompose.{name}"
        artifacts[PACKAGE / name / "generated_components.py"] = (
            render_python_components(part, package)
        )
        artifacts[PACKAGE / name / "__init__.py"] = render_python_exports(part, package)
    artifacts[KOTLIN_ADAPTERS_PATH] = render_generated_adapters(registry)
    artifacts[ROOT / KOTLIN_DRIVES_RELATIVE] = render_holder_drives(registry)
    artifacts[ROOT / KOTLIN_VALUES_RELATIVE.with_name("GeneratedModifiers.kt")] = (
        render_modifiers(registry)
    )
    artifacts[PACKAGE / "ui/scoped_modifiers.py"] = render_scoped_operations(registry)
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Regenerate the artifacts derived from schema/catalog.lock.json.")
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify derived artifacts are up to date; exit non-zero on drift (CI).",
    )
    parser.add_argument(
        "--app",
        type=Path,
        metavar="DIR",
        help=(
            "Generate only the components DIR uses, into DIR itself (ADR-0014). "
            "Discovery is by name in the AST; an app that stops referencing a "
            "component stops shipping it."
        ),
    )
    args = parser.parse_args(argv)
    if args.app is not None:
        return build_app(args.app, check=args.check)
    registry = load_registry()
    artifacts = framework_artifacts(registry)
    if args.check:
        drifted = [
            str(artifact)
            for artifact, expected in artifacts.items()
            if _read(artifact) != expected
        ]
        if drifted:
            for artifact in drifted:
                print(
                    f"gen.py: drift detected: {artifact} is out of date",
                    file=sys.stderr,
                )
            return 1
        return 0
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"gen.py: regenerated {len(artifacts)} artifact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
