"""Hash-owned resource outputs; user files and edits are never overwritten."""

import hashlib
import json
import re

from pycompose_cli.project import Project, ProjectError, project_path, read_json
from pycompose_cli.project.resources import MAIN, resource_files

MANIFEST = ".pycompose/resource-sync.json"


def _owned(project: Project) -> dict[str, str]:
    path = project_path(project.root, MANIFEST)
    if not path.exists():
        return {}
    data = read_json(path)
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "files"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or not isinstance(data["files"], dict)
    ):
        raise ProjectError("invalid resource ownership manifest", path=MANIFEST)
    owned: dict[str, str] = {}
    main = (project.android_root.relative_to(project.root) / MAIN).as_posix()
    for name, digest in data["files"].items():
        if (
            not isinstance(name, str)
            or not name.startswith((f"{main}/res/", f"{main}/assets/"))
            or not isinstance(digest, str)
            or re.fullmatch(r"[a-f0-9]{64}", digest) is None
        ):
            raise ProjectError("invalid resource ownership entry", path=name)
        project_path(project.root, name)
        owned[name] = digest
    return owned


def sync_resources(project: Project, *, check: bool = False) -> tuple[str, ...]:
    """Synchronize project resource outputs, or detect drift without writing.

    Args:
        project: Loaded project configuration.
        check: Report drift only; do not modify files or directories.

    Returns:
        Names of generated files or ownership records whose bytes differ.

    Raises:
        ProjectError: If an output is unmanaged, locally modified or unsafe.
    """
    output = resource_files(project)
    owned = _owned(project)
    expected = {
        name: hashlib.sha256(value).hexdigest()
        for name, value in sorted(output.items())
    }
    manifest = (
        json.dumps(
            {"version": 1, "files": expected}, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")
    changed: set[str] = set()
    stale: list[str] = []
    for name in sorted(output.keys() | owned.keys()):
        destination = project_path(project.root, name)
        if destination.exists():
            if not destination.is_file():
                raise ProjectError("resource output is not a file", path=name)
            if name not in owned:
                raise ProjectError(
                    "refusing to overwrite unmanaged resource", path=name
                )
            if hashlib.sha256(destination.read_bytes()).hexdigest() != owned[name]:
                raise ProjectError(
                    "generated resource was locally modified; resolve it before sync",
                    path=name,
                )
            if name not in output:
                stale.append(name)
        if name in output and (
            not destination.exists() or owned.get(name) != expected[name]
        ):
            changed.add(name)
    manifest_path = project_path(project.root, MANIFEST)
    manifest_changed = (
        not manifest_path.is_file() or manifest_path.read_bytes() != manifest
    )
    if check:
        return tuple(
            sorted([*changed, *stale, *([MANIFEST] if manifest_changed else [])])
        )
    for name, value in sorted(output.items()):
        if name not in changed:
            continue
        destination = project_path(project.root, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(value)
    for name in stale:
        project_path(project.root, name).unlink()
    if manifest_changed:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(manifest)
    return tuple(sorted([*changed, *stale, *([MANIFEST] if manifest_changed else [])]))
