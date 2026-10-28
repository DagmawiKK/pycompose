"""The debug input log: every host input, in order, with what it produced.

Each entry names the runtime call, its arguments and a digest of the snapshot
it left behind. Replaying the entries against a fresh session must reproduce
every digest; the first one that differs points at the input where behaviour
stopped being a function of its inputs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

__all__ = ["Entry", "InputLog", "digest"]


def digest(snapshot: str) -> str:
    """Return a short, stable fingerprint of a snapshot.

    Args:
        snapshot: Canonical snapshot JSON, or empty before any snapshot.

    Returns:
        Sixteen hex digits.
    """
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Entry:
    """One host input and the snapshot it left behind.

    Attributes:
        call: The runtime function the host called.
        args: Its positional arguments, as the host passed them.
        kwargs: Its keyword arguments.
        snapshot: The digest of the snapshot afterwards.
    """

    call: str
    args: tuple[object, ...]
    kwargs: dict[str, object]
    snapshot: str


@dataclass(slots=True)
class InputLog:
    """The inputs of one debug session, in the order the loop took them."""

    entries: list[Entry] = field(default_factory=list)

    def add(
        self,
        call: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        snapshot: str,
    ) -> None:
        """Record one input and the snapshot it produced.

        Args:
            call: The runtime function the host called.
            args: Its positional arguments.
            kwargs: Its keyword arguments.
            snapshot: The snapshot afterwards.
        """
        self.entries.append(Entry(call, args, kwargs, digest(snapshot)))

    def dumps(self) -> str:
        """Return the log as JSON lines.

        Returns:
            One JSON object per input.
        """
        return "".join(
            json.dumps(
                {
                    "call": e.call,
                    "args": list(e.args),
                    "kwargs": e.kwargs,
                    "snapshot": e.snapshot,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for e in self.entries
        )

    @staticmethod
    def loads(text: str) -> list[Entry]:
        """Read a log written by :meth:`dumps`.

        Args:
            text: JSON lines.

        Returns:
            The entries, in order.
        """
        entries = []
        for line in text.splitlines():
            if line.strip():
                raw = json.loads(line)
                entries.append(
                    Entry(
                        raw["call"],
                        tuple(raw["args"]),
                        dict(raw["kwargs"]),
                        raw["snapshot"],
                    )
                )
        return entries
