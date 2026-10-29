"""Single-worker desktop preview; it never substitutes for device-owned State."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

from pycompose.app.app import App
from pycompose.bridge.session import compose_once
from pycompose_cli.project import Project, ProjectError, project_path


class AppReloader:
    """Reload only user modules and produce a diagnostic full IR snapshot."""

    def __init__(self, project: Project) -> None:
        config = project.table("python")
        directory = config.get("source_dir", "app")
        entrypoint = config.get("entrypoint", "main:app")
        if (
            not isinstance(directory, str)
            or not isinstance(entrypoint, str)
            or re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", entrypoint)
            is None
        ):
            raise ProjectError("invalid python.source_dir or python.entrypoint")
        self.directory = project_path(project.root, directory)
        self._module, self._function = entrypoint.split(":")
        self._loaded = False
        self._path = str(self.directory)
        if not self.directory.is_dir():
            raise ProjectError("Python source directory is missing", path=directory)
        # A module of a name the app defines, imported from elsewhere (another
        # app's generated ``m3``), would be found before the app's own: set it
        # aside for the session, as ``fresh_imports`` does, and restore it after.
        names = {
            path.stem
            for path in self.directory.iterdir()
            if path.suffix == ".py" or path.is_dir()
        }
        self._hidden = {
            name: module
            for name, module in sys.modules.items()
            if name.split(".")[0] in names
        }
        for name in self._hidden:
            del sys.modules[name]
        sys.path.insert(0, self._path)

    def _modules(self) -> list[ModuleType]:
        modules = []
        for module in tuple(sys.modules.values()):
            filename = getattr(module, "__file__", None)
            if (
                module is not None
                and isinstance(filename, str)
                and Path(filename).resolve().is_relative_to(self.directory)
            ):
                modules.append(module)
        return modules

    def _reload_order(self) -> list[ModuleType]:
        modules = {module.__name__: module for module in self._modules()}
        edges: dict[str, set[str]] = {}
        for name, module in modules.items():
            dependencies: set[str] = set()
            filename = module.__file__
            if filename is not None and Path(filename).is_file():
                for node in ast.walk(
                    ast.parse(Path(filename).read_text(encoding="utf-8"))
                ):
                    if isinstance(node, ast.Import):
                        dependencies.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        prefix = (
                            importlib.util.resolve_name(
                                "." * node.level + (node.module or ""),
                                module.__package__ or "",
                            )
                            if node.level
                            else node.module or ""
                        )
                        dependencies.add(prefix)
                        dependencies.update(
                            f"{prefix}.{alias.name}" for alias in node.names
                        )
            edges[name] = dependencies.intersection(modules.keys()) - {name}
        ordered = []
        while edges:
            ready = sorted(name for name, deps in edges.items() if not deps)
            if not ready:
                raise ProjectError(
                    "cyclic user imports require restarting the app for reload"
                )
            for name in ready:
                ordered.append(modules[name])
                del edges[name]
            for deps in edges.values():
                deps.difference_update(ready)
        return ordered

    def snapshot(self) -> str:
        """Re-import user code and validate a canonical snapshot on this worker.

        Returns:
            Complete canonical JSON, without timestamps or diagnostic metadata.

        Raises:
            ProjectError: If the entrypoint names no ``App`` export, or the app
                produces no valid snapshot.
        """
        # Timestamp-based bytecode can otherwise hide rapid, equal-length edits.
        for path in self.directory.rglob("*.py"):
            cache = Path(importlib.util.cache_from_source(str(path)))
            project_path(self.directory, cache.relative_to(self.directory).as_posix())
            if cache.is_file() and not cache.is_symlink():
                cache.unlink()
        importlib.invalidate_caches()
        if self._loaded:
            # Reload dependencies first so from-import aliases see current values.
            for module in self._reload_order():
                if module.__file__ is not None and Path(module.__file__).is_file():
                    retained = {
                        key: value
                        for key, value in vars(module).items()
                        if key.startswith("__")
                    }
                    vars(module).clear()
                    vars(module).update(retained)
                    importlib.reload(module)
                else:
                    sys.modules.pop(module.__name__, None)
        self._loaded = True
        module = importlib.import_module(self._module)
        self._modules()
        app = getattr(module, self._function, None)
        if not isinstance(app, App):
            raise ProjectError(
                "entrypoint must name the module's pycompose.app.App export",
                entrypoint=f"{self._module}:{self._function}",
            )
        # Composed as a device session composes it: its start screen, with a
        # container of its own, on a loop thread that ends with it.
        snapshot, error = compose_once(f"{self._module}:{self._function}")
        if not snapshot:
            raise ProjectError("app did not produce a valid snapshot", error=error)
        return snapshot

    def close(self) -> None:
        """Remove session-owned user modules and restore the import path."""
        for module in self._modules():
            sys.modules.pop(module.__name__, None)
        if self._path in sys.path:
            sys.path.remove(self._path)
        sys.modules.update(self._hidden)
