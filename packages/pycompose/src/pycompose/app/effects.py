"""Typed one-shot requests for the host: at-most-once, never replayed.

An effect may be lost if the process dies before the host runs it, so anything
that must happen belongs in state instead. The effects themselves are generated
from the catalog (:mod:`pycompose.app.generated_effects`); this is their base.
"""

from __future__ import annotations

from typing import ClassVar

from pycompose.model.nodes.effect import Effect
from pycompose.model.nodes.props import to_camel_case

__all__ = ["TypedEffect"]


class TypedEffect:
    """A typed effect: its kind, and its fields as the effect's payload.

    Attributes:
        kind: The registered effect kind.
    """

    kind: ClassVar[str]

    def effect(self) -> Effect:
        """Return the effect the host runs.

        Returns:
            The registered effect kind with this effect's fields, by wire name.
        """
        payload = {to_camel_case(name): value for name, value in vars(self).items()}
        return Effect(self.kind, payload)
