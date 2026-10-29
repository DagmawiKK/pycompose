"""The domain layer, tested on its own.

This module exists to prove a boundary, not to test behaviour for its own sake.
If a use case ever needed a file, a screen, or the library, one of these tests
would fail -- and that is the whole claim: the rules of the app can be exercised
without anything that stores them, and without knowing what stores it.

Nothing here imports ``notes_app.data``, ``notes_app.views`` or ``pycompose``. The
store is written by hand against the Protocol for exactly that reason: importing
the shipped implementation would drag the runtime in with it.

The Phase 4 acceptance bar, in one sentence: a use case runs here with an
in-memory repository and no data layer in the process.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

APP = Path(__file__).resolve().parents[1] / "examples" / "notes" / "app"

if TYPE_CHECKING:
    from notes_app.domain.models import Note


@pytest.fixture(scope="module", autouse=True)
def _app_on_path(request: pytest.FixtureRequest) -> None:
    """Put the example app on the import path for this module.

    Args:
        request: The fixture request, used to schedule the teardown.

    Returns:
        None, once the teardown is scheduled.
    """
    sys.path.insert(0, str(APP))
    request.addfinalizer(lambda: sys.path.remove(str(APP)))


@pytest.fixture(scope="module")
def domain() -> object:
    """Import the domain layer exactly as the app does.

    Returns:
        The domain package.
    """
    import notes_app.domain as layer

    return layer


@pytest.fixture
def store() -> Any:
    """Return an in-memory repository, declared here rather than imported.

    Written against the Protocol by hand, on purpose. Its only extra member is
    ``highest_id``, which the identity rule needs and a real backend also has.

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

        def insert(self, note: Note) -> None:
            """Keep one new note.

            Args:
                note: The note, with the identity it took.
            """
            self.notes.append(note)
            self.writes += 1
            self.mark = max(self.mark, note.id)

        def update(self, note: Note) -> None:
            """Replace one note.

            Args:
                note: The note as it is now.
            """
            self.notes = [note if held.id == note.id else held for held in self.notes]
            self.writes += 1

        def delete(self, note_id: int) -> None:
            """Drop one note.

            Args:
                note_id: The note to remove.
            """
            self.notes = [held for held in self.notes if held.id != note_id]
            self.writes += 1

        def close(self) -> None:
            """Nothing to release."""

    return Store()


@pytest.fixture
def notes(store: Any) -> Any:
    """Return the use cases, bound to this test's store.

    This is the whole shape of a ViewModel in a Kotlin app: the use cases are
    constructed once with their dependency, and the caller holds the use cases.

    Args:
        store: The repository the use cases should hold.

    Returns:
        The app's note use cases.
    """
    from notes_app.domain import Notes

    return Notes(store)


# ---------------------------------------------------------------------------
# Ordering and description
# ---------------------------------------------------------------------------


def test_notes_are_listed_newest_first(store: Any) -> None:
    from notes_app.domain import Notes
    from notes_app.domain.models import Note

    store.notes = [Note(1, "Older"), Note(3, "Newest"), Note(2, "Middle")]
    notes = Notes(store)
    assert [note.title for note in notes.list()] == ["Newest", "Middle", "Older"]


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "Nothing saved yet"), (1, "1 note"), (2, "2 notes"), (9, "9 notes")],
)
def test_the_count_line_describes_what_is_held(
    domain: object, count: int, expected: str
) -> None:
    from notes_app.domain.models import Note

    assert domain.count_line([Note(index) for index in range(count)]) == expected


# ---------------------------------------------------------------------------
# Creating
# ---------------------------------------------------------------------------


def test_creating_a_note_returns_the_id_it_took(notes: Any, store: Any) -> None:
    assert (notes.create("First"), notes.create("Second")) == (1, 2)
    assert len(store.load()) == 2


def test_ids_are_never_reused_after_a_deletion(notes: Any) -> None:
    """Reusing one would let a stale control write into its replacement."""
    from notes_app.domain.models import Note

    notes.create("First")
    notes.delete(1)

    assert notes.create("Different") == 2
    assert notes.get(2) == Note(2, "Different")


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def test_renaming_and_retexting_change_only_what_was_asked(store: Any) -> None:
    from notes_app.domain import Notes
    from notes_app.domain.models import Note

    store.notes = [Note(1, "Before", "text"), Note(2, "Other", "kept")]
    notes = Notes(store)
    notes.rename(1, "After")
    notes.retext(1, "other")

    assert notes.get(1) == Note(1, "After", "other")
    # Storage is told about the one note that changed, once per change.
    assert store.load() == [Note(1, "After", "other"), Note(2, "Other", "kept")]
    assert store.writes == 2


def test_the_note_is_immutable_rather_than_edited_in_place() -> None:
    from notes_app.domain.models import Note

    original = Note(1, "Before", "text")
    assert original.retitled("After") == Note(1, "After", "text")
    assert original.title == "Before"


def test_editing_something_that_is_gone_does_nothing(store: Any) -> None:
    """A control can outlive the note it was bound to; that must be harmless."""
    from notes_app.domain import Notes
    from notes_app.domain.models import Note

    store.notes = [Note(1, "Untouched")]
    notes = Notes(store)
    notes.rename(99, "Wrong")
    notes.retext(99, "Wrong")
    notes.delete(99)

    assert store.load() == [Note(1, "Untouched")]
    assert store.writes == 0


# ---------------------------------------------------------------------------
# The guarantees this file exists for
# ---------------------------------------------------------------------------


def test_a_caller_never_sees_the_repository() -> None:
    """The dependency is bound once, in the constructor, and then hidden."""
    from notes_app.domain import Notes
    from notes_app.domain.models import Note

    assert [name for name in vars(Notes) if not name.startswith("_")] == [
        "list",
        "get",
        "create",
        "rename",
        "retext",
        "delete",
    ]
    assert Note(1).id == 1


def test_the_domain_offers_exactly_what_the_actions_call(domain: object) -> None:
    """One front door, and it is the whole vocabulary an action needs."""
    assert set(domain.__all__) == {
        "Note",
        "Notes",
        "NotesRepo",
        "count_line",
        "newest_first",
    }


def test_a_view_model_names_a_use_case_and_never_a_repository() -> None:
    """The direction Clean Architecture insists on, asserted on the source.

    A view model holding a repository would assemble the use case's own
    dependency itself. That is dependency passing, not injection.
    """
    source = "".join(
        path.read_text(encoding="utf-8")
        for path in (APP / "notes_app" / "view_models").glob("*.py")
    )
    assert "NotesRepo" not in source
    assert "notes_repo" not in source
    assert "notes: Notes" in source


def test_only_the_wiring_names_a_backend() -> None:
    """Outside the module that defines it, one file names a backend.

    ``data/notes_repo.py`` defines it and ``data/__init__.py`` re-exports it;
    nothing else in the app may, which is what makes swapping storage a change to
    one line rather than a search.
    """
    hits = sorted(
        path.relative_to(APP).as_posix()
        for path in (APP / "notes_app").rglob("*.py")
        if "SqliteNotesRepo" in path.read_text(encoding="utf-8")
    )
    assert hits == [
        "notes_app/container.py",
        "notes_app/data/__init__.py",
        "notes_app/data/notes_repo.py",
    ]


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


# ---------------------------------------------------------------------------
# The shipped backends still satisfy what the domain asks for
# ---------------------------------------------------------------------------


def test_the_shipped_backends_satisfy_the_protocol_structurally(
    tmp_path: Path,
) -> None:
    """No base class, no registration: the shape is the contract."""
    from notes_app.data.notes_repo import MemoryNotesRepo, SqliteNotesRepo
    from notes_app.domain.models import NotesRepo

    assert isinstance(MemoryNotesRepo(), NotesRepo)
    assert isinstance(SqliteNotesRepo(tmp_path / "notes.db"), NotesRepo)


def test_the_database_writes_one_row_per_change_and_never_reuses_an_id(
    tmp_path: Path,
) -> None:
    """What a session wrote is what the next one reads, deletions remembered."""
    from notes_app.data.notes_repo import SqliteNotesRepo
    from notes_app.domain import Notes
    from notes_app.domain.models import Note

    from pycompose.testing.simulator import Simulator

    path = tmp_path / "notes.db"
    sim = Simulator()

    async def first_session() -> None:
        notes = Notes(SqliteNotesRepo(path))
        notes.create("First")
        notes.create("Second")
        notes.rename(2, "Renamed")
        notes.delete(1)

    sim.run(first_session())
    sim.settle()
    sim.close()

    repo = SqliteNotesRepo(path)
    assert repo.load() == [Note(2, "Renamed", "")]
    assert repo.highest_id() == 2

    async def second_session() -> int:
        return Notes(repo).create("Third")

    sim = Simulator()
    assert sim.run(second_session()) == 3
    sim.close()
