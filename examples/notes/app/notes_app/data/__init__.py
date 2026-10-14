"""The data layer: how notes are actually kept.

Two implementations behind the domain's Protocol. The file-backed one is what
ships; the in-memory one exists so the domain can be tested, and so a demo or a
preview has somewhere to point that never touches disk.
"""

from __future__ import annotations

from notes_app.data.notes_repo import FileNotesRepo, MemoryNotesRepo

__all__ = ["FileNotesRepo", "MemoryNotesRepo"]
