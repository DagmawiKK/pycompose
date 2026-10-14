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
    entrypoint = python.get("entrypoint", "main:build")
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
