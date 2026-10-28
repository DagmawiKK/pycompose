"""StateFlow: one observable value, conflated, read with ``async for``."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Generic, TypeVar

__all__ = ["StateFlow"]

T = TypeVar("T")
R = TypeVar("R")


class StateFlow(Generic[T]):
    """A value that collectors follow: each sees the current value, then each change.

    Collectors are conflated: one that falls behind sees the latest value, never
    a backlog. Setting a value equal to the current one notifies nobody.

    Args:
        value: The initial value.
    """

    def __init__(self, value: T) -> None:
        self._value = value
        self._version = 0
        self._waiters: list[asyncio.Future[None]] = []

    @property
    def value(self) -> T:
        """The current value.

        Returns:
            The value collectors last saw or will see next.
        """
        return self._value

    @value.setter
    def value(self, value: T) -> None:
        if value == self._value:
            return
        self._value = value
        self._version += 1
        waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)

    async def __aiter__(self) -> AsyncIterator[T]:
        seen = -1
        while True:
            if self._version != seen:
                seen = self._version
                yield self._value
                continue
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
            await waiter

    def map(self, transform: Callable[[T], R]) -> AsyncIterator[R]:
        """Follow ``transform`` of each value.

        Args:
            transform: Applied to each value as it is seen.

        Returns:
            An iterator of the transformed values, conflated like this flow.
        """

        async def mapped() -> AsyncIterator[R]:
            async for value in self:
                yield transform(value)

        return mapped()
