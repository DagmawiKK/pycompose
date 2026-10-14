"""Durable storage: the seam between app state and disk.

``State.data`` travels through the host's ``SavedStateHandle``, which is a
``Bundle``. That is a fine place for the session shell — route, appearance, a
draft — and the wrong place for anything else. A thousand notes do not belong in
a transaction buffer, and the failure mode when they do is a
``TransactionTooLargeException`` that names nothing useful.

So the split is:

* the **shell** stays in ``State.data``, small enough to always survive;
* everything else lives in a repository, on disk, of any size.

The host owns the directory and Python opens files in it, so a repository needs no
host API of its own. Everything here is plain data in and plain data out; no
objects cross, and the boundary stays where ADR-0001 put it.

    notes = Document("notes.json", Note)     # a dataclass, stored as JSON

Writes are atomic: a document is written to a temporary file and renamed over the
old one, so a process killed mid-write leaves the previous version intact rather
than half a file. A document that is unreadable anyway — corrupted, truncated,
or written by a newer version — reads as empty and says so, because a notes app
that cannot start is worse than one that starts empty.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator, Sequence
from dataclasses import is_dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar, cast, runtime_checkable

from pycompose.errors import StateError
from pycompose.state.app_state import Codec
from pycompose.utils.json_canonical import canonical_json

__all__ = [
    "Document",
    "Repository",
    "diagnostics",
    "root",
    "use_root",
]

T = TypeVar("T")

_override: Path | None = None
_diagnostics: list[str] = []
_lock = threading.RLock()


def root() -> Path:
    """Return the directory this app's documents live in.

    On Android that is the app's private files directory, which Chaquopy exposes.
    Elsewhere it is ``PYCOMPOSE_HOME`` if set, and the working directory if not,
    so tests and the CLI work without a device.

    Returns:
        The directory, which may not exist yet.
    """
    if _override is not None:
        return _override
    try:
        # Imported by name rather than written as an import statement: Chaquopy
        # exists only inside an APK, and a type checker run against the source
        # tree should not have to be told about it.
        app_dir = import_module("chaquopy").dir
    except (ImportError, AttributeError):
        pass
    else:
        return Path(app_dir())
    return Path(os.environ.get("PYCOMPOSE_HOME", Path.cwd()))


def use_root(path: Path | str) -> None:
    """Point the library's documents at another directory.

    Args:
        path: The directory to use instead. Created on first write.
    """
    global _override  # noqa: PLW0603 -- process-wide, like the worker
    with _lock:
        _override = Path(path)


def diagnostics() -> tuple[str, ...]:
    """Return what storage has had to report.

    Returns:
        One line per problem, oldest first.
    """
    with _lock:
        return tuple(_diagnostics)


def _note(message: str) -> None:
    """Record a storage problem for the host to surface.

    Args:
        message: What went wrong, in plain language.
    """
    with _lock:
        _diagnostics.append(message)


@runtime_checkable
class Repository(Protocol):
    """The shape a store implements. Structural: no base class is required.

    Declaring this is documentation and a type-checker's business; nothing
    registers against it, and an in-memory implementation satisfies it as
    completely as a file-backed one.
    """

    def load(self) -> list[Any]:
        """Return everything held.

        Returns:
            The stored items.
        """
        ...  # pragma: no cover - protocol declaration

    def save(self, items: list[Any]) -> None:
        """Replace everything held.

        Args:
            items: The items to keep.
        """
        ...  # pragma: no cover - protocol declaration


def _codec_for(model: Any) -> Codec:
    """Return the codec describing a model.

    Args:
        model: A dataclass, or any type a ``Codec`` already describes.

    Returns:
        The codec for that type.

    Raises:
        StateError: If the model is not a type this codec can carry.
    """
    if isinstance(model, Codec):
        return model
    if not (isinstance(model, type) and is_dataclass(model)):
        raise StateError(f"{model!r} is not a dataclass this store can carry")
    return Codec(cast("type", model))


class Document(Generic[T]):
    """One JSON document on disk, holding a list of one model.

    The app works with its own type; the file holds plain JSON. Nothing about the
    directory or the file format is visible to the app, which is what makes the
    backend replaceable.
    """

    def __init__(
        self,
        name: str,
        model: Any,
        *,
        directory: Path | str | None = None,
    ) -> None:
        """Open, without creating, a document.

        Args:
            name: File name within the storage root.
            model: The dataclass each item is.
            directory: Where to keep it, defaulting to the storage root.

        Raises:
            StateError: If the name or model is unusable.
        """
        if not name or Path(name).name != name:
            raise StateError("document name must be a plain file name")
        self._codec = _codec_for(model)
        self._path = Path(directory) / name if directory is not None else root() / name

    @property
    def path(self) -> Path:
        """Return where this document lives.

        Returns:
            The file path.
        """
        return self._path

    def load(self) -> list[T]:
        """Return every item held.

        A document that is absent, unreadable, or not what this app expects
        reads as empty rather than raising: a corrupt save must leave the user
        with a working app, not a stack trace on boot.

        Returns:
            The stored items.
        """
        with _lock:
            return cast("list[T]", self._read())

    def save(self, items: Sequence[T]) -> None:
        """Replace everything held, atomically.

        Args:
            items: The items to keep. A failure to write raises rather than
                losing the caller's data silently.
        """
        encoded = [self._codec.encode(item) for item in items]
        text = canonical_json(encoded)
        with _lock:
            self._write(text)

    def _read(self) -> list[object]:
        """Return the document's contents, or empty when unusable.

        Returns:
            The decoded items.
        """
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            _note(f"cannot read {self._path.name}: {exc}")
            return []
        if not raw.strip():
            return []
        import json

        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            _note(f"{self._path.name} is not readable JSON: {exc}")
            return []
        if not isinstance(decoded, list):
            _note(f"{self._path.name} does not hold a list")
            return []
        usable: list[object] = []
        for entry in decoded:
            try:
                usable.append(self._codec.decode(entry))
            except Exception as exc:  # one bad item must not lose the rest
                _note(f"{self._path.name} holds an item this app cannot read: {exc}")
        return usable

    def _write(self, text: str) -> None:
        """Write the document, replacing the old one atomically.

        Args:
            text: The canonical JSON to store.

        Raises:
            StateError: If the file cannot be written.
        """
        temporary = self._path.with_name(f"{self._path.name}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, self._path)
        except OSError as exc:
            _note(f"cannot write {self._path.name}: {exc}")
            raise StateError(f"cannot write {self._path.name}: {exc}") from exc

    def __iter__(self) -> Iterator[T]:
        """Return an iterator over the stored items.

        Returns:
            An iterator over the document.
        """
        return iter(self.load())
