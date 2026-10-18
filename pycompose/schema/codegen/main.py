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

from pycompose.schema.codegen.rules import (
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

ROOT = Path(__file__).resolve().parents[3]

IR_SCHEMA_PATH = ROOT / "schema" / "ir.schema.json"
BUNDLED_SCHEMA_PATH = ROOT / "pycompose" / "schema" / "ir.schema.json"
BUNDLED_CATALOG_PATH = PACKAGED_CATALOG
VALIDATORS_PATH = ROOT / "pycompose" / "ir" / "generated_validators.py"
PAYLOADS_PATH = ROOT / "pycompose" / "bridge" / "generated_payloads.py"
KOTLIN_ADAPTERS_PATH = (
    ROOT / "android/host/src/main/kotlin/com/pycompose/host/ui/GeneratedAdapters.kt"
)

KOTLIN_MODELS_PATH = (
    ROOT / "android/ir/src/main/kotlin/com/pycompose/ir/generated/UiModels.kt"
)
KOTLIN_REGISTRY_PATH = (
    ROOT / "android/ir/src/main/kotlin/com/pycompose/ir/generated/IrContract.kt"
)
PYTHON_COMPONENTS_PATH = ROOT / "pycompose/m3/generated_components.py"
PYTHON_EXPORTS_PATH = ROOT / "pycompose/m3/__init__.py"
KOTLIN_VALUES_RELATIVE = Path(
    "android/renderer/src/main/kotlin/com/pycompose/renderer/generated/ValueResolver.kt"
)


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

    Returns:
        Process exit code: 0 clean, 1 on drift or an unresolvable app.
    """
    from pycompose.schema.codegen.app_slice import (
        _ADAPTERS_RELATIVE,
        _IR_RELATIVE,
        _VALUES_RELATIVE,
        APP_PACKAGE,
        FLOOR_COMPONENTS,
        AppCodegenError,
        discover,
        discover_values,
        load_catalog,
        slice_registry,
    )
    from pycompose.schema.codegen.emit_kotlin import (
        render_generated_adapters,
        render_kotlin_models,
        render_kotlin_registry,
    )
    from pycompose.schema.codegen.emit_python import (
        render_python_components,
        render_python_exports,
    )
    from pycompose.schema.codegen.values import render_python
    from pycompose.schema.codegen.values_kotlin import (
        render_models,
        render_native,
    )

    native = python_root if android_root is None else android_root
    for root in (python_root, native):
        if not root.is_dir():
            print(f"gen.py: not a directory: {root}", file=sys.stderr)
            return 1
    try:
        registry = load_catalog(SCHEMA_PATH)
        used = discover(python_root, registry)
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
        python_root / package / "generated_components.py": (
            render_python_components(sliced, package)
        ),
        python_root / package / "__init__.py": render_python_exports(sliced, package),
        python_root / package / "values.py": render_python(sliced),
        native / _IR_RELATIVE / "UiModels.kt": render_kotlin_models(sliced),
        native / _IR_RELATIVE / "IrContract.kt": render_kotlin_registry(sliced),
        native / _IR_RELATIVE / "ValueModels.kt": render_models(sliced),
        native / _VALUES_RELATIVE: render_native(sliced),
        native / _ADAPTERS_RELATIVE: render_generated_adapters(sliced),
    }

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
    from pycompose.schema.codegen.app_slice import FLOOR_COMPONENTS

    if not used:
        return f"{app} references no components; nothing to generate"
    floorless = FLOOR_COMPONENTS.difference(registry["components"])
    if floorless:
        return (
            "catalog is missing components every host compiles against: "
            + ", ".join(sorted(floorless))
        )
    return None


def _mirror_template(artifacts: dict[Path, str]) -> None:
    """Mirror every module counterpart into the template, in place.

    The template is the project ``pycompose init`` scaffolds, and it carries the
    framework sources verbatim. Whatever the modules have is what a generated app
    gets, so every counterpart is mirrored -- not just the generated half, which
    would ship a project whose renderer predates its adapters.

    A counterpart this run regenerated is copied from ``artifacts`` rather than
    read back from disk: disk still holds the previous run's output, so reading
    the file would mirror content one generation behind.

    Args:
        artifacts: The run's pending artifacts, keyed by path; template copies
            are added to it and generated copies are reused as-is.
    """
    template = ROOT / "pycompose/templates/android"
    for path in sorted(template.rglob("*")):
        if not path.is_file() or path in artifacts:
            continue
        source = ROOT / "android" / path.relative_to(template)
        if not source.is_file():
            continue
        generated = artifacts.get(source)
        if generated is not None:
            artifacts[path] = generated
            continue
        raw = source.read_bytes()
        try:
            contents = raw.decode("utf-8")
        except UnicodeDecodeError:
            contents = None
        if contents is None or "\r" in contents:
            # Not plain LF text: the Gradle wrapper jar is not source at all,
            # and gradlew.bat keeps its CRLF line endings. `pycompose init`
            # copies both, and tests/test_template_parity.py compares them byte
            # for byte -- it sees what a text artifact cannot.
            continue
        artifacts[path] = contents


def framework_artifacts(registry: dict[str, Any]) -> dict[Path, str]:
    """Build every framework artifact one generation emits, without touching disk.

    Args:
        registry: The validated catalog mapping.

    Returns:
        Artifact paths keyed to their full rendered content; the template
        mirror is added by :func:`_mirror_template` on top of this mapping.
    """
    from pycompose.schema.codegen.emit_kotlin import (
        render_generated_adapters,
        render_kotlin_models,
        render_kotlin_registry,
    )
    from pycompose.schema.codegen.emit_python import (
        render_payloads,
        render_python_components,
        render_python_exports,
        render_validators,
    )
    from pycompose.schema.codegen.emit_wire import render_ir_schema
    from pycompose.schema.codegen.values import render_python as render_values
    from pycompose.schema.codegen.values_kotlin import (
        render_models,
        render_native,
    )

    artifacts = {
        IR_SCHEMA_PATH: render_ir_schema(registry),
        BUNDLED_SCHEMA_PATH: render_ir_schema(registry),
        BUNDLED_CATALOG_PATH: SCHEMA_PATH.read_text(encoding="utf-8"),
        VALIDATORS_PATH: render_validators(registry),
        PAYLOADS_PATH: render_payloads(registry),
        KOTLIN_MODELS_PATH: render_kotlin_models(registry),
        KOTLIN_REGISTRY_PATH: render_kotlin_registry(registry),
        PYTHON_COMPONENTS_PATH: render_python_components(registry),
        PYTHON_EXPORTS_PATH: render_python_exports(registry),
        ROOT / "pycompose/values.py": render_values(registry),
        KOTLIN_MODELS_PATH.with_name("ValueModels.kt"): render_models(registry),
        ROOT / KOTLIN_VALUES_RELATIVE: render_native(registry),
    }
    artifacts[KOTLIN_ADAPTERS_PATH] = render_generated_adapters(registry)
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate schema/ir.schema.json and "
            "pycompose/ir/generated_validators.py."
        )
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
    _mirror_template(artifacts)
    for fixture in sorted((ROOT / "pycompose/testing/fixtures").glob("*.json")):
        # The repository's own tests read these through the modules' test
        # source sets. A scaffold ships no framework tests, so the template
        # carries none.
        relative = Path("ir/src/test/resources") / fixture.name
        artifacts[ROOT / "android" / relative] = fixture.read_text(encoding="utf-8")
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
