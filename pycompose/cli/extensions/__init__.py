"""Read-only extension planning; discovery never imports integration code.

Planning and evidence live beside the command that reports them, not in the
``pycompose.extensions`` runtime package: nothing on a device reads a definition
or an evidence record, and an application ships only the runtime package.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pycompose.cli.extensions.definition import Definition, plan
from pycompose.cli.extensions.evidence import (
    EvidenceRecord,
    Target,
    fingerprint,
    load_records,
    summarize,
)
from pycompose.cli.permissions import (
    effective_permissions,
    selected_permissions,
    stage_manifest,
)
from pycompose.cli.project import Project, ProjectError, project_path
from pycompose.cli.requirements import validate_requirements
from pycompose.errors import StateError
from pycompose.version import __version__

#: Bundled definitions ship with the library metadata, never with an app.
BUNDLED_DEFINITIONS = (
    Path(__file__).resolve().parents[2] / "integrations" / "definitions"
)

#: The locked framework target; a build or device observation is authoritative.
#: One typed value, so the plan report, the fingerprints and the status check
#: cannot disagree about what "this target" means.
TARGET = Target(python="3.12", abis=("arm64-v8a", "x86_64"), min_sdk=24)
#: Project-local evidence documents are read, never written, by the CLI.
EVIDENCE_FILE = "evidence.json"
#: Declared scenarios carry no revision field yet, so the contract is pinned here
#: and a bump is what invalidates evidence for an unchanged scenario id.
SCENARIO_VERSION = 1


def _definitions(project: Project) -> list[Definition]:
    """Load explicitly selected definitions without importing their code.

    Args:
        project: App configuration with optional extension definitions.

    Returns:
        The validated definitions in selection order.

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
            path = BUNDLED_DEFINITIONS / f"{key}.toml"
        else:
            path = project_path(project.root, name)
        definitions.append(Definition.parse(path.read_text(encoding="utf-8")))
    return definitions


def scenario_fingerprints(
    project: Project, definitions: list[Definition] | None = None
) -> dict[str, str]:
    """Digest the declared inputs each scenario's evidence depends on.

    Args:
        project: App configuration supplying target and template facts.
        definitions: Loaded definitions; read from the project when omitted.

    Returns:
        Fingerprint per declared scenario identity.

    Raises:
        ProjectError: If definition selection or configuration is invalid.
    """
    chosen = _definitions(project) if definitions is None else definitions
    template = project.table("toolchain").get("template_version", "")
    if not isinstance(template, str):
        raise ProjectError("toolchain.template_version must be a string")
    permissions = list(selected_permissions(project))
    return {
        scenario: fingerprint(
            {
                "framework": __version__,
                "template": template,
                "extension": definition.id,
                "definitionVersion": definition.version,
                "requirements": list(definition.requirements),
                "scenario": scenario,
                "scenarioVersion": SCENARIO_VERSION,
                "python": TARGET.python,
                "abis": list(TARGET.abis),
                "minSdk": TARGET.min_sdk,
                "permissions": permissions,
            }
        )
        for definition in chosen
        for scenario in definition.scenarios
    }


def _records(project: Project) -> tuple[EvidenceRecord, ...]:
    """Read the project-local evidence document when one exists.

    Args:
        project: App configuration naming the evidence file.

    Returns:
        Validated records, or none when the project has no document yet.

    Raises:
        ProjectError: If the document exists but cannot be validated.
    """
    path = project_path(project.root, EVIDENCE_FILE)
    if not path.is_file():
        return ()
    try:
        return load_records(path.read_text(encoding="utf-8"))
    except StateError as exc:
        raise ProjectError(str(exc)) from exc


def evidence_view(
    project: Project, definitions: list[Definition]
) -> tuple[dict[str, dict[str, object]], dict[str, int]]:
    """Report every declared scenario's observed evidence status.

    Args:
        project: App configuration with optional extension definitions.
        definitions: Loaded definitions whose scenarios are declared.

    Returns:
        Declared scenario statuses and their per-status counts. A record only
        verifies the target it was observed on.
    """
    return summarize(
        {definition.id: definition.scenarios for definition in definitions},
        scenario_fingerprints(project, definitions),
        _records(project),
        TARGET,
    )


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
        ProjectError: If definition paths, selection values or observed evidence
            are invalid. An unreadable definition file is reported as a project
            error rather than escaping as a raw OS error.
    """
    try:
        definitions = _definitions(project)
    except OSError as exc:
        raise ProjectError(f"cannot read extension definitions: {exc}") from exc
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
    report["target"] = TARGET.to_json()
    report["targetBasis"] = "framework defaults; actual Android build is authoritative"
    observed, summary = evidence_view(project, definitions)
    # The flat "evidence" field stays the planner's own claim: nothing here has
    # run resolution, packaging, import or operations. Per-scenario observed
    # status is reported beside it, never merged into a project-wide verdict.
    report["observed"], report["observedSummary"] = observed, summary
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


def show_evidence(project: Project) -> int:
    """Print observed scenario evidence without running any scenario.

    Args:
        project: Selected app configuration.

    Returns:
        Zero when the report is readable; missing records read as untested.
    """
    definitions = _definitions(project)
    view, counts = evidence_view(project, definitions)
    print(
        json.dumps(
            {
                "document": str(project_path(project.root, EVIDENCE_FILE)),
                "evidence": view,
                "summary": counts,
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0
