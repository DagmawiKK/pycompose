"""Read-only extension planning; discovery never imports integration code."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pycompose.cli.permissions import (
    effective_permissions,
    selected_permissions,
    stage_manifest,
)
from pycompose.cli.project import Project, ProjectError, project_path
from pycompose.cli.requirements import validate_requirements
from pycompose.extensions.definition import Definition, plan


def _host_errors(project: Project, *, selected: bool, modules: bool) -> list[str]:
    errors = []
    if modules or selected_permissions(project):
        gradle = project_path(project.android_root, "host/build.gradle.kts")
        text = gradle.read_text(encoding="utf-8")
        if "pycomposeIntegrationModules" not in text or "pycomposeManifest" not in text:
            errors.append(
                "selected extensions need a host with extension build hooks; "
                "create a new native scaffold"
            )
    if selected:
        version = project.table("toolchain").get("template_version", "")
        valid = isinstance(version, str) and re.fullmatch(r"\d+\.\d+\.\d+", version)
        if not valid or tuple(map(int, str(version).split("."))) < (0, 7, 0):
            errors.append("extensions require template_version 0.7.0 or newer")
    return errors


def extension_plan(project: Project) -> dict[str, object]:
    """Load explicitly selected definitions and report missing runtime contracts.

    Args:
        project: App configuration with optional extension definitions.

    Returns:
        A JSON-compatible capability report, without compatibility endorsements.

    Raises:
        ProjectError: If definition paths or selection values are invalid.
    """
    selected = project.table("extensions").get("definitions", [])
    if not isinstance(selected, list) or not all(isinstance(x, str) for x in selected):
        raise ProjectError("extensions.definitions must be an array of paths")
    definitions = []
    for name in selected:
        if name.startswith("builtin:"):
            key = name.removeprefix("builtin:")
            if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
                raise ProjectError("invalid bundled extension name")
            path = (
                Path(__file__).parents[1] / "integrations/definitions" / f"{key}.toml"
            )
        else:
            path = project_path(project.root, name)
        definitions.append(Definition.parse(path.read_text(encoding="utf-8")))
    capabilities = {
        "python.blocking": 1,
        "python.serial": 1,
        "python.actions": 1,
    }
    if definitions or selected_permissions(project):
        permissions = effective_permissions(project)
        if "android.permission.INTERNET" in permissions:
            capabilities["android.internet"] = 1
    report = plan(tuple(definitions), capabilities)
    errors = report["errors"]
    checks = report["checks"]
    assert isinstance(errors, list) and isinstance(checks, dict)
    errors.extend(
        _host_errors(
            project, selected=bool(definitions), modules=bool(report["modules"])
        )
    )
    checks["capabilities"] = "failed" if errors else "passed"
    report["requirements"] = validate_requirements(
        report["requirements"], field="extension.requirements"
    )
    report["target"] = {"python": "3.12", "abis": ["arm64-v8a", "x86_64"], "minSdk": 24}
    report["targetBasis"] = "framework defaults; actual Android build is authoritative"
    return report


def check_extensions(project: Project) -> dict[str, object]:
    """Reject unavailable requirements before a build changes files.

    Args:
        project: Selected project and native host.

    Returns:
        The read-only plan if its required capabilities are available.

    Raises:
        ProjectError: If required capabilities or native build hooks are missing.
    """
    report = extension_plan(project)
    errors = report["errors"]
    assert isinstance(errors, list)
    if errors:
        raise ProjectError("missing extension capabilities: " + ", ".join(errors))
    return report


def stage_extensions(project: Project, env: dict[str, str]) -> None:
    """Supply generic module selection and generated manifest inputs to Gradle.

    Args:
        project: Project already admitted by check_extensions.
        env: Build environment receiving data-only Gradle properties.
    """
    report = extension_plan(project)
    env.pop("ORG_GRADLE_PROJECT_pycomposeManifest", None)
    modules = report["modules"]
    assert isinstance(modules, list)
    env["ORG_GRADLE_PROJECT_pycomposeIntegrationModules"] = "\n".join(
        module.rsplit(".", 1)[1] for module in modules
    )
    manifest = stage_manifest(project)
    if manifest is not None:
        env["ORG_GRADLE_PROJECT_pycomposeManifest"] = str(manifest)


def show_plan(project: Project) -> int:
    """Print a machine-readable plan and signal missing required capabilities.

    Args:
        project: Selected app configuration.

    Returns:
        Zero if requirements are satisfied, two otherwise.
    """
    report = extension_plan(project)
    print(json.dumps(report, sort_keys=True, indent=2))
    return 2 if report["errors"] else 0
