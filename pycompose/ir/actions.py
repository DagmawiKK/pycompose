"""Action queue for host -> Python actions."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

__all__ = ["Action", "ActionQueue"]


@dataclass(frozen=True, slots=True)
class Action:
    action_id: str
    payload: dict[str, Any]
    version: int = 0


class ActionQueue:
    def __init__(self) -> None:
        self._queue: deque[Action] = deque()

    def push(self, action: Action) -> None:
        if not isinstance(action, Action):
            raise TypeError("action must be an Action instance")
        self._queue.append(action)

    def pop(self) -> Action:
        return self._queue.popleft()

    def size(self) -> int:
        return len(self._queue)

    def empty(self) -> bool:
        return len(self._queue) == 0
