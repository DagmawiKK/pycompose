"""Programs by reference: each program once per snapshot, named by its content.

A program is data a prop carries, but the same one recurs: one draw function on
every row of a list, and on every snapshot while its bound arguments change.
So a snapshot carries each program once, in its ``programs`` section keyed by
the SHA-256 of the program's canonical bytes, and a prop names it as
``{"type": "ref", "hash": <hash>}``. A section the host already holds is kept
rather than sent again, as every metadata section is, so a program crosses
once until the set a screen uses changes.

Emission lifts programs out of props (:func:`lift`); validation, on either
side, puts them back (:func:`resolve`) and judges them where they are used.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import cast

from pycompose.errors import IrValidationError
from pycompose.model.canonical import canonical_json_bytes
from pycompose.model.programs.drawing import DRAW, validate_drawing
from pycompose.model.programs.functions import validate_function

PROGRAMS = "programs"
"""The metadata section holding a snapshot's programs, by hash."""

PROGRAMS_SINCE = "1.23.0"
"""The first schema whose snapshots carry programs."""

Declare = Callable[[str, object], None]
"""Receives each lifted program and its hash."""


def program_hash(program: object) -> str:
    """Name a program by its content.

    Args:
        program: A program's wire form.

    Returns:
        The SHA-256 of its canonical bytes, in hex.
    """
    return hashlib.sha256(canonical_json_bytes(program)).hexdigest()


def lift(value: object, declare: Declare) -> object:
    """Replace each program in a value by a reference to it.

    Args:
        value: A prop's value.
        declare: Receives each program found and its hash.

    Returns:
        The same object when it holds no program, else a copy holding refs.
    """
    if isinstance(value, Mapping) and value.get("type") == "program":
        name = program_hash(value)
        declare(name, value)
        return {"type": "ref", "hash": name}
    return _each(value, lambda item: lift(item, declare))


def resolve(value: object, programs: Mapping[str, object]) -> object:
    """Put back each program a value names by reference.

    Args:
        value: A prop's value, as a snapshot carries it.
        programs: The snapshot's programs, by hash.

    Returns:
        The same object when it names none, else a copy holding the programs.

    Raises:
        IrValidationError: If a reference names a program the snapshot lacks.
    """
    if isinstance(value, Mapping) and value.get("type") == "ref":
        name = value.get("hash")
        if set(value) != {"type", "hash"}:
            raise IrValidationError("a ref is {type: ref, hash}")
        if not isinstance(name, str) or name not in programs:
            raise IrValidationError(f"no program {name!r} in the snapshot")
        return programs[name]
    return _each(value, lambda item: resolve(item, programs))


def read_programs(metadata: Mapping[str, object] | None) -> Mapping[str, object]:
    """Check a snapshot's programs section: each named by its content, and sound.

    Args:
        metadata: The snapshot's metadata, or None.

    Returns:
        The programs by hash; empty when the snapshot carries none.

    Raises:
        IrValidationError: If a program is malformed or misnamed.
    """
    section = (metadata or {}).get(PROGRAMS)
    if section is None:
        return {}
    if not isinstance(section, Mapping):
        raise IrValidationError("programs is a map from hash to program")
    for name, program in section.items():
        if not isinstance(program, Mapping) or program_hash(program) != name:
            raise IrValidationError(f"program {name!r} is not named by its content")
        (validate_drawing if program.get("result") == DRAW else validate_function)(
            program
        )
    return cast("Mapping[str, object]", section)


def _each(value: object, change: Callable[[object], object]) -> object:
    """A container with ``change`` applied to each member, or itself unchanged."""
    if isinstance(value, Mapping):
        items = {key: change(item) for key, item in value.items()}
        return value if all(items[k] is value[k] for k in items) else items
    if isinstance(value, list | tuple):
        members = [change(item) for item in value]
        return (
            value
            if all(a is b for a, b in zip(members, value, strict=True))
            else members
        )
    return value
