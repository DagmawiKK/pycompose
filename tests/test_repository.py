"""Durable storage: documents, atomicity, corruption, and size.

The last of those is the point of the seam. Ten thousand notes must survive
without anything being asked to carry them in a Bundle.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from pycompose.errors import StateError
from pycompose.storage.documents import Document, diagnostics, root, use_root


@dataclass(frozen=True)
class Note:
    """A stored item.

    Attributes:
        id: Its identity.
        title: Its headline.
        body: Its text.
    """

    id: int
    title: str = ""
    body: str = ""


@pytest.fixture(autouse=True)
def _temp_root(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    """Point storage at a temporary directory for the duration of one test.

    Args:
        tmp_path: The temporary directory.
        request: The fixture request, used to schedule the teardown.
    """
    use_root(tmp_path)
    request.addfinalizer(lambda: use_root(Path.cwd()))


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------


def test_a_document_survives_a_round_trip(tmp_path: Path) -> None:
    document = Document("notes.json", Note)
    document.save([Note(1, "First"), Note(2, "Second", "more")])

    assert document.load() == [Note(1, "First"), Note(2, "Second", "more")]
    assert document.path.parent == tmp_path


def test_a_document_that_was_never_written_is_empty() -> None:
    assert Document("missing.json", Note).load() == []


def test_reading_does_not_require_the_directory_to_exist(tmp_path: Path) -> None:
    """A document may live in a directory that has not been created yet."""
    nested = tmp_path / "never-created"
    assert Document("gone.json", Note, directory=nested).load() == []


def test_saving_creates_the_directory() -> None:
    use_root(Path(os.environ.get("TMPDIR", "/tmp")) / "pycompose-not-created")
    document = Document("notes.json", Note)
    document.save([Note(1)])
    assert document.load() == [Note(1)]
    use_root(Path.cwd())


def test_an_item_is_written_as_plain_json(tmp_path: Path) -> None:
    Document("notes.json", Note).save([Note(1, "First")])
    raw = json.loads((tmp_path / "notes.json").read_text())
    assert raw == [{"id": 1, "title": "First", "body": ""}]


def test_iterating_yields_what_is_stored() -> None:
    Document("notes.json", Note).save([Note(1), Note(2)])
    assert list(Document("notes.json", Note)) == [Note(1), Note(2)]


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------


def test_a_write_replaces_the_previous_one_atomically(tmp_path: Path) -> None:
    """A process killed mid-write must leave the old version, not half a file."""
    document = Document("notes.json", Note)
    document.save([Note(1, "before")])
    document.save([Note(1, "after")])

    assert document.load() == [Note(1, "after")]
    # No temporary file is left behind for the next write to trip over.
    assert not (tmp_path / "notes.json.tmp").exists()


def test_writing_is_reported_when_the_directory_cannot_be_made() -> None:
    blocked = Document("notes.json", Note, directory="/proc/nope/deeper")
    with pytest.raises(StateError, match="cannot write"):
        blocked.save([Note(1)])
    assert any("cannot write" in line for line in diagnostics())


def test_two_documents_do_not_share_a_file() -> None:
    Document("a.json", Note).save([Note(1, "a")])
    Document("b.json", Note).save([Note(2, "b")])
    assert Document("a.json", Note).load() == [Note(1, "a")]
    assert Document("b.json", Note).load() == [Note(2, "b")]


# ---------------------------------------------------------------------------
# Corruption degrades, it does not crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "   ",
        "not json at all",
        '{"notes": [1, 2]}',
        '{"id": 1, "title": "x"}',
        "null",
        "42",
    ],
)
def test_an_unusable_document_reads_as_empty(tmp_path: Path, contents: str) -> None:
    (tmp_path / "notes.json").write_text(contents)
    assert Document("notes.json", Note).load() == []


def test_one_unreadable_item_does_not_lose_the_others(tmp_path: Path) -> None:
    """A single bad record is skipped, not allowed to empty the store."""
    (tmp_path / "notes.json").write_text(
        json.dumps([{"id": 1, "title": "kept", "body": ""}, {"title": "no id"}])
    )
    assert Document("notes.json", Note).load() == [Note(1, "kept")]


def test_a_corrupt_document_is_reported(tmp_path: Path) -> None:
    (tmp_path / "notes.json").write_text("definitely not json")
    Document("notes.json", Note).load()
    assert any("not readable JSON" in line for line in diagnostics())


# ---------------------------------------------------------------------------
# Names that would escape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["../escape.json", "sub/dir.json", "", "/abs.json"])
def test_a_name_cannot_escape_the_storage_root(name: str) -> None:
    with pytest.raises(StateError, match="plain file name"):
        Document(name, Note)


def test_a_model_that_is_not_a_dataclass_is_refused() -> None:
    with pytest.raises(StateError, match="dataclass"):
        Document("notes.json", int)


# ---------------------------------------------------------------------------
# The reason this seam exists
# ---------------------------------------------------------------------------


def test_ten_thousand_notes_survive(tmp_path: Path) -> None:
    """The acceptance bar: durable data of any size, with no Bundle involved."""
    notes = [Note(index, f"Note {index}", "x" * 200) for index in range(10_000)]
    document = Document("notes.json", Note)
    document.save(notes)

    size = (tmp_path / "notes.json").stat().st_size
    reloaded = document.load()
    assert len(reloaded) == 10_000
    assert reloaded[9_999] == notes[9_999]
    # Far past what a Bundle would carry, which is exactly why it is on disk.
    assert size > 1024 * 1024


def test_the_storage_root_is_the_app_directory_and_can_be_overridden(
    tmp_path: Path,
) -> None:
    use_root(tmp_path)
    assert root() == tmp_path


def test_the_storage_root_is_the_app_directory_on_a_device(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Chaquopy exposes the app's private files directory, and that is the root.

    The module is faked rather than imported: it exists only inside an APK.
    """
    android = ModuleType("java.android")
    android.context = SimpleNamespace(getFilesDir=lambda: str(tmp_path))
    monkeypatch.setitem(sys.modules, "java.android", android)
    monkeypatch.setattr("pycompose.storage.documents._override", None)

    assert root() == tmp_path


def test_a_bridge_without_context_falls_back_to_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A hollow ``java.android`` must not shadow the documented fallback."""
    monkeypatch.setitem(sys.modules, "java.android", ModuleType("java.android"))
    monkeypatch.setattr("pycompose.storage.documents._override", None)
    monkeypatch.setenv("PYCOMPOSE_HOME", str(tmp_path / "env"))

    assert root() == tmp_path / "env"


def test_a_document_may_live_outside_the_root(tmp_path: Path) -> None:
    """Explicit placement, for an app that keeps some data elsewhere."""
    elsewhere = tmp_path / "other"
    document = Document("notes.json", Note, directory=elsewhere)
    document.save([Note(1)])
    assert document.load() == [Note(1)]
    assert document.path == elsewhere / "notes.json"


def test_diagnostics_are_bounded_so_a_failing_loop_cannot_leak() -> None:
    """A background pass that fails every time would otherwise grow forever."""
    from pycompose.storage.documents import DIAGNOSTIC_HISTORY

    document = Document("notes.json", Note, directory="/proc/nope/deeper")
    for _ in range(DIAGNOSTIC_HISTORY * 3):
        with pytest.raises(StateError):
            document.save([Note(1)])

    kept = diagnostics()
    assert len(kept) == DIAGNOSTIC_HISTORY


def test_the_newest_diagnostics_are_the_ones_kept() -> None:
    """Oldest goes first, so what survives explains what is happening now."""
    from pycompose.storage.documents import DIAGNOSTIC_HISTORY

    # Alternate names so each failure is distinguishable in the history.
    names = [f"note_{index % 4}.json" for index in range(DIAGNOSTIC_HISTORY * 2)]
    for name in names:
        with pytest.raises(StateError):
            Document(name, Note, directory="/proc/nope/deeper").save([Note(1)])

    kept = diagnostics()
    assert len(kept) == DIAGNOSTIC_HISTORY
    # The tail of what was written, in the order it was written.
    expected = names[-DIAGNOSTIC_HISTORY:]
    assert [line.split(":")[0].split()[-1] for line in kept] == expected


def test_an_unchanged_document_shares_its_items_until_it_is_written() -> None:
    """Immutable items are decoded once, so views keyed by identity see no change."""
    document = Document("notes.json", Note)
    document.save([Note(1, "First")])
    first, again = document.load(), document.load()
    assert first is not again
    assert first[0] is again[0]

    document.save([Note(1, "Renamed")])
    assert document.load() == [Note(1, "Renamed")]
