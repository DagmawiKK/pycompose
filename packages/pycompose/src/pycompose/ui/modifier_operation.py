"""The descriptor that makes a modifier operation callable on the class too."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Concatenate, Generic, ParamSpec

if TYPE_CHECKING:
    from pycompose.ui.modifier import Modifier

P = ParamSpec("P")


class _Operation(Generic[P]):
    """A modifier operation callable on a chain or on the class itself.

    ``Modifier.padding(20)`` starts a chain as Compose's ``Modifier.padding``
    does, and ``Modifier().padding(20)`` continues an existing one; both are
    the same operation.
    """

    def __init__(self, function: Callable[Concatenate[Modifier, P], Modifier]) -> None:
        self.function = function
        self.__doc__ = function.__doc__

    def __get__(
        self, instance: Modifier | None, owner: type[Modifier]
    ) -> Callable[P, Modifier]:
        return partial(self.function, owner() if instance is None else instance)
