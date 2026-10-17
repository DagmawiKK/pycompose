"""Gradle packaging with environment-only signing properties and redacted logs."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

from pycompose.cli.project import (
    Project,
    ProjectError,
    check_project_versions,
    project_path,
)
from pycompose.cli.sync import sync_resources

SIGNING_PREFIX = "ORG_GRADLE_PROJECT_android.injected.signing."

_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_EXTRAS = r"(?:\[" + _NAME + r"(?:," + _NAME + r")*\])?"
_OPERATOR = r"(?:===|==|!=|~=|<=|>=|<|>)"
_VERSION = r"[A-Za-z0-9][A-Za-z0-9.*+!_-]*"
_SPECIFIER = r"\s*" + _OPERATOR + r"\s*" + _VERSION
_REQUIREMENT = re.compile(
    _NAME + _EXTRAS + r"(?:" + _SPECIFIER + r"(?:," + _SPECIFIER + r")*)?"
    r"(?:\s*;\s*\S.*)?"
)
_ARCHIVE_SUFFIXES = (".whl", ".tar.gz", ".zip")
# First Android template whose host installs app requirements; older scaffolds
# have no pip block and would drop a declared requirement without a word.
_MIN_REQUIREMENTS_TEMPLATE = (0, 4, 0)


def _requirements(project: Project) -> list[str]:
    """Validate the app's declared package requirements.

    Requirements are data the host's Chaquopy pip block installs at build
    time: pure-Python packages and Android wheels available for the app's
    Python version and ABIs. Only named package specifiers are accepted here,
    so a mistyped path, pip option or wheel filename fails with one message
    instead of an obscure Gradle error.

    Args:
        project: Project with an optional [python] requirements array.

    Returns:
        The stripped requirement specifiers, in declaration order.

    Raises:
        ProjectError: If the array or one of its entries is not a specifier.
    """
    requirements = project.table("python").get("requirements", [])
    if not isinstance(requirements, list):
        raise ProjectError("python.requirements must be an array of package specifiers")
    result = []
    for index, requirement in enumerate(requirements):
        if (
            not isinstance(requirement, str)
            or not requirement.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in requirement)
        ):
            raise ProjectError(
                "python.requirements entries must be nonempty single-line strings",
                index=index,
            )
        stripped = requirement.strip()
        if stripped.casefold().endswith(_ARCHIVE_SUFFIXES):
            raise ProjectError(
                "python.requirements accepts named packages; build a wheel with "
                "Chaquopy's toolchain and publish or mirror it to install it by name",
                index=index,
            )
        if _REQUIREMENT.fullmatch(stripped) is None:
            raise ProjectError(
                "python.requirements entries must be pip package specifiers: "
                "name, extras, version and optional environment marker",
                index=index,
            )
        result.append(stripped)
    return result


def _scaffold_template_version(project: Project) -> tuple[int, ...] | None:
    """Parse the project's template version, or None when it is unreadable.

    Args:
        project: Project with a toolchain table.

    Returns:
        Numeric version parts, or None when the field is absent or malformed.
    """
    value = project.table("toolchain").get("template_version")
    if not isinstance(value, str):
        return None
    parts = value.split(".")
    if any(re.fullmatch(r"\d+", part) is None for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _check_requirements_scaffold(project: Project, requirements: list[str]) -> None:
    """Refuse requirements on a scaffold that would silently drop them.

    Hosts generated before dependency support have no pip block, so declared
    requirements would reach Gradle and vanish without a word. That failure is
    silent, so it is raised here instead, before Gradle starts.

    Args:
        project: Project whose scaffold installs the requirements.
        requirements: Validated requirement specifiers.

    Raises:
        ProjectError: If requirements are declared on an older template.
    """
    if not requirements:
        return
    version = _scaffold_template_version(project)
    if version is not None and version >= _MIN_REQUIREMENTS_TEMPLATE:
        return
    raise ProjectError(
        "python.requirements needs an Android scaffold from template 0.4.0 or "
        "newer; create a project with pycompose init and copy its host/ over "
        "this one's so the app installs what it declares",
        template_version="unknown" if version is None else ".".join(map(str, version)),
    )


def _app_properties(project: Project, env: dict[str, str]) -> None:
    config = project.table("app")
    app_id = config.get("application_id")
    version_name = config.get("version_name")
    version_code = config.get("version_code")
    if (
        not isinstance(app_id, str)
        or re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", app_id) is None
    ):
        raise ProjectError("app.application_id must be an Android package name")
    if not isinstance(version_name, str) or not version_name or "\0" in version_name:
        raise ProjectError("app.version_name must be a nonempty string")
    if type(version_code) is not int or not 1 <= version_code <= 2_100_000_000:
        raise ProjectError("app.version_code must be a positive Android version code")
    env["ORG_GRADLE_PROJECT_pycomposeApplicationId"] = app_id
    env["ORG_GRADLE_PROJECT_pycomposeVersionName"] = version_name
    env["ORG_GRADLE_PROJECT_pycomposeVersionCode"] = str(version_code)
    python = project.table("python")
    entrypoint = python.get("entrypoint", "main:app")
    source = python.get("source_dir", "app")
    if (
        not isinstance(entrypoint, str)
        or re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", entrypoint)
        is None
    ):
        raise ProjectError("invalid python.entrypoint")
    if not isinstance(source, str):
        raise ProjectError("invalid python.source_dir")
    directory = project_path(project.root, source)
    if not directory.is_dir():
        raise ProjectError("Python source directory is missing", path=directory)
    env["ORG_GRADLE_PROJECT_pycomposeEntrypoint"] = entrypoint
    env["ORG_GRADLE_PROJECT_pycomposeSourceDir"] = str(directory)
    requirements = _requirements(project)
    _check_requirements_scaffold(project, requirements)
    env["ORG_GRADLE_PROJECT_pycomposeRequirements"] = "\n".join(requirements)
    env["ORG_GRADLE_PROJECT_pycomposeRuntimeDir"] = str(
        Path(__file__).resolve().parents[2]
    )


def _signing(project: Project, env: dict[str, str]) -> tuple[str, ...]:
    config = project.table("signing")
    values = {}
    for field in ("keystore", "key_alias", "store_password_env", "key_password_env"):
        value = config.get(field)
        if not isinstance(value, str) or not value or "\0" in value:
            raise ProjectError(
                "release signing requires a configured field", field=f"signing.{field}"
            )
        values[field] = value
    keystore = Path(values["keystore"]).expanduser()
    if not keystore.is_absolute():
        keystore = project.root / keystore
    if not keystore.is_file():
        raise ProjectError("release keystore is missing", path=keystore)
    secrets = []
    for field, prop in (
        ("store_password_env", "store.password"),
        ("key_password_env", "key.password"),
    ):
        value = env.get(values[field])
        if not value:
            raise ProjectError(
                "release signing environment variable is missing",
                variable=values[field],
            )
        env[SIGNING_PREFIX + prop] = value
        secrets.append(value)
    env[SIGNING_PREFIX + "store.file"] = str(keystore.resolve())
    env[SIGNING_PREFIX + "key.alias"] = values["key_alias"]
    return tuple(secrets)


def _redacted(text: str, secrets: tuple[str, ...]) -> str:
    for value in sorted(secrets, key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    return text


def _artifacts(project: Project, kind: str, variant: str) -> tuple[Path, ...]:
    folder = "apk" if kind == "apk" else "bundle"
    root = project_path(project.root, f"host/build/outputs/{folder}/{variant}")
    result = []
    for path in sorted(root.rglob(f"*.{kind}")):
        project_path(project.root, path.relative_to(project.root).as_posix())
        try:
            with zipfile.ZipFile(path) as archive:
                expected = (
                    {"AndroidManifest.xml"}
                    if kind == "apk"
                    else {"base/manifest/AndroidManifest.xml", "BundleConfig.pb"}
                )
                if not expected <= set(archive.namelist()):
                    raise ProjectError(
                        "Gradle output is not an Android artifact", path=path
                    )
        except zipfile.BadZipFile as exc:
            raise ProjectError(
                "Gradle output is not a valid ZIP artifact", path=path
            ) from exc
        if variant == "release" and path.name.endswith("-unsigned.apk"):
            raise ProjectError("Gradle produced an unsigned release APK", path=path)
        result.append(path)
    if not result:
        raise ProjectError("Gradle succeeded but produced no artifact", path=root)
    return tuple(result)


def _codegen(project: Project) -> None:
    """Regenerate the app's component slice before Gradle runs (ADR-0014).

    Bound to the build because a slice that is regenerated on demand is never
    stale, and one that must be regenerated by hand is stale within a week.
    Generated code is build output now, and a build that reads output from
    something other than the build is the arrangement ADR-0014 replaced.

    Only runs for an app that has adopted per-app codegen -- one importing its
    own generated package. An app on the library catalog has nothing to
    generate, and starting to fail those builds would be a regression dressed
    up as an improvement.

    Args:
        project: The project being built.

    Raises:
        ProjectError: If the slice cannot be generated.
    """
    from pycompose.schema.codegen.app_slice import uses_generated_slice
    from pycompose.schema.codegen.main import build_app

    python = project.table("python")
    source = python.get("source_dir", "app")
    if not isinstance(source, str):
        raise ProjectError("invalid python.source_dir")
    directory = project_path(project.root, source)
    if not uses_generated_slice(directory):
        return
    if build_app(directory, android_root=project.root) != 0:
        raise ProjectError("component slice generation failed", path=directory)


def build_project(
    project: Project, *, kind: str = "apk", release: bool = False
) -> tuple[Path, ...]:
    """Sync resources, invoke the host Gradle task, and locate its artifacts.

    Args:
        project: Project containing a root Gradle wrapper and host module.
        kind: apk or aab output.
        release: Require configured signing and build the release variant.

    Returns:
        Output artifact paths; installability still requires native integration.

    Raises:
        ProjectError: If scaffold, signing, Gradle execution or output is invalid.
    """
    if kind not in {"apk", "aab"}:
        raise ProjectError("build format must be apk or aab")
    check_project_versions(project)
    wrapper = project_path(
        project.root, "gradlew.bat" if os.name == "nt" else "gradlew"
    )
    if not wrapper.is_file() or not any(
        (project.root / name).is_file()
        for name in ("settings.gradle.kts", "settings.gradle")
    ):
        raise ProjectError(
            "Android scaffold is missing; build requires the Gradle wrapper "
            "and host integration tickets"
        )
    if os.name != "nt" and not os.access(wrapper, os.X_OK):
        raise ProjectError("Gradle wrapper is not executable; run chmod +x gradlew")
    env = dict(os.environ)
    _app_properties(project, env)
    secrets = _signing(project, env) if release else ()
    sync_resources(project)
    _codegen(project)
    variant = "release" if release else "debug"
    task = f":host:{'assemble' if kind == 'apk' else 'bundle'}{variant.title()}"
    result = subprocess.run(
        [str(wrapper), task, "--console=plain", "--no-daemon"],
        cwd=project.root,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    print(_redacted(result.stdout, secrets), end="")
    print(_redacted(result.stderr, secrets), end="", file=sys.stderr)
    if result.returncode:
        raise ProjectError("Gradle task failed", task=task, exit_code=result.returncode)
    return _artifacts(project, kind, variant)
