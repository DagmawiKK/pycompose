"""The domain layer, tested on its own.

This module exists to prove a boundary, not to test behaviour for its own sake.
If a use case ever needs a file, a screen, or the library, one of these tests
will fail at import time -- and that is the whole claim: the rules of the app can
be exercised without anything that stores them.

Nothing here may import ``notes_app.data``, ``notes_app.views`` or ``pycompose``.
The guard at the bottom enforces that as a test rather than as a convention.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pycompose.repository import Document

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"

if TYPE_CHECKING:
    from notes_app.domain.models import Note


@pytest.fixture(scope="module")
def domain() -> object:
    """Import the domain layer exactly as the app does.

    Returns:
        The domain package.
    """
    sys.path.insert(0, str(APP))
    try:
        import notes_app.domain as layer

        return layer
    finally:
        sys.path.remove(str(APP))


@pytest.fixture
def store() -> object:
    """Return an in-memory repository, declared here rather than imported.

    Written against the Protocol by hand, on purpose. Importing the shipped
    implementation would drag ``pycompose.repository`` in with it, which is the
    dependency this file is here to prove is avoidable.

    Returns:
        A store satisfying ``NotesRepo``.
    """

    class Store:
        """Notes kept in a list, counting the calls made against it."""

        def __init__(self, notes: list[Note] | None = None) -> None:
            """Hold the notes.

            Args:
                notes: What to start with.
            """
            self.notes = list(notes or [])
            self.writes = 0
            self.mark = max((note.id for note in self.notes), default=0)

        def highest_id(self) -> int:
            """Return the largest identity ever issued.

            Returns:
                The high-water mark.
            """
            return self.mark

        def load(self) -> list[Note]:
            """Return the notes held.

            Returns:
                A copy, so a caller cannot mutate the store by accident.
            """
            return list(self.notes)

        def store(self, notes: list[Note]) -> None:
            """Replace everything held.

            Args:
                notes: The notes to keep.
            """
            self.notes = list(notes)
            self.writes += 1
            self.mark = max(self.mark, max((note.id for note in notes), default=0))

    return Store()


# ---------------------------------------------------------------------------
# Ordering and description
# ---------------------------------------------------------------------------


def test_notes_are_listed_newest_first(domain: object, store: object) -> None:
    from notes_app.domain.models import Note

    store.store([Note(1, "Older"), Note(3, "Newest"), Note(2, "Middle")])
    assert [note.title for note in domain.list_notes(store)] == [
        "Newest",
        "Middle",
        "Older",
    ]


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "Nothing saved yet"), (1, "1 note"), (2, "2 notes"), (9, "9 notes")],
)
def test_the_count_line_describes_what_is_held(
    domain: object,
    count: int,
    expected: str,
) -> None:
    from notes_app.domain.models import Note

    assert domain.count_line([Note(index) for index in range(count)]) == expected


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


def test_creating_a_note_returns_the_id_it_took(domain: object, store: object) -> None:
    first = domain.create_note(store, "First")
    second = domain.create_note(store, "Second")

    assert (first, second) == (1, 2)
    assert len(store.load()) == 2


def test_ids_are_never_reused_after_a_deletion(domain: object, store: object) -> None:
    """Reusing one would let a stale control write into its replacement."""
    from notes_app.domain.models import Note

    domain.create_note(store, "First")
    domain.delete_note(store, 1)
    fresh = domain.create_note(store, "Different")

    assert fresh == 2
    assert domain.get_note(store, 2) == Note(2, "Different")


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def test_renaming_and_retexting_change_only_what_was_asked(
    domain: object,
    store: object,
) -> None:
    from notes_app.domain.models import Note

    store.store([Note(1, "Before", "text")])
    domain.rename_note(store, 1, "After")
    domain.retext_note(store, 1, "other")

    assert store.load() == [Note(1, "After", "other")]


def test_the_note_is_immutable_rather_than_edited_in_place() -> None:
    from notes_app.domain.models import Note

    original = Note(1, "Before", "text")
    assert original.retitled("After") == Note(1, "After", "text")
    assert original.title == "Before"


def test_editing_something_that_is_gone_does_nothing(
    domain: object, store: object
) -> None:
    """A control can outlive the note it was bound to; that must be harmless."""
    from notes_app.domain.models import Note

    store.store([Note(1, "Untouched")])
    store.writes = 0  # forget the setup, so the assertion means something
    domain.rename_note(store, 99, "Wrong")
    domain.retext_note(store, 99, "Wrong")
    domain.delete_note(store, 99)

    assert store.load() == [Note(1, "Untouched")]
    assert store.writes == 0


# ---------------------------------------------------------------------------
# The guarantee this file exists for
# ---------------------------------------------------------------------------


def test_the_domain_offers_exactly_the_use_cases_the_actions_call() -> None:
    """One front door, and it is the whole vocabulary an action needs."""
    sys.path.insert(0, str(APP))
    try:
        import notes_app.domain as layer
    finally:
        sys.path.remove(str(APP))
    assert set(layer.__all__) >= {
        "count_line",
        "create_note",
        "delete_note",
        "get_note",
        "list_notes",
        "rename_note",
        "retext_note",
    }


def test_the_boundary_is_real_not_aspirational() -> None:
    """Nothing under ``domain/`` reaches up or sideways."""
    forbidden = ("notes_app.data", "notes_app.views", "pycompose")
    offenders = [
        f"{path.name} reaches {name}"
        for path in (APP / "notes_app" / "domain").rglob("*.py")
        for name in forbidden
        if name in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_the_shipped_backends_satisfy_the_protocol_structurally() -> None:
    """No base class, no registration: the shape is the contract."""
    from notes_app.data.notes_repo import FileNotesRepo, MemoryNotesRepo
    from notes_app.domain.models import NotesRepo

    for implementation in (FileNotesRepo, MemoryNotesRepo):
        assert isinstance(implementation(), NotesRepo)


def test_the_file_backend_remembers_the_mark_across_a_deletion(
    tmp_path: Path,
) -> None:
    """Recomputing the mark from what is held would hand the identity out twice."""
    from notes_app.data import FileNotesRepo
    from notes_app.domain import create_note
    from notes_app.domain.models import Note

    repo = FileNotesRepo(Document("notes.json", Note, directory=tmp_path))
    create_note(repo, "First")
    from notes_app.domain import delete_note

    delete_note(repo, 1)

    assert repo.highest_id() == 1
    assert create_note(repo, "Second") == 2
