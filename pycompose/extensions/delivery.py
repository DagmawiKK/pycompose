"""Worker-owned one-shot registrations for data-only background outcomes.

Tickets travel as registered action ids on the existing queue, not as hidden
fields in an application's payload. Admission happens again on the state worker.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from pycompose import async_task
from pycompose.core.action_binding import check_payload
from pycompose.core.props import to_camel_case
from pycompose.errors import StateError
from pycompose.state.app_action import AppAction
from pycompose.utils.json_canonical import canonical_json

_PREFIX = "pycompose.task."
_current: ContextVar[Dispatcher | None] = ContextVar(
    "extension_dispatcher", default=None
)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous outcome JSON")
        result[key] = value
    return result


def _payload(values: object, target: AppAction[Any]) -> dict[str, object]:
    if not isinstance(values, Mapping):
        raise StateError("extension action result must be a mapping")
    payload = {to_camel_case(key): value for key, value in values.items()}
    if len(payload) != len(values):
        raise StateError("extension payload names collide")
    check_payload(payload, target.fields)
    return payload


def current() -> Dispatcher | None:
    """Return the dispatcher active on this worker's action transition.

    Returns:
        The current dispatcher, or None outside an action.
    """
    return _current.get()


class Ticket:
    """One registered completion, held until acknowledgement or logical disposal."""

    def __init__(
        self,
        dispatcher: Dispatcher,
        settle: Callable[[], None],
        success: AppAction[Any] | None,
        failure: AppAction[Any] | None,
        encode: Callable[[Any], Mapping[str, object]] | None,
        error: Callable[[Exception], Mapping[str, object]] | None,
    ) -> None:
        self.dispatcher, self.settle = dispatcher, settle
        self.success, self.failure = success, failure
        self.encode, self.error = encode, error
        self.id = _PREFIX + uuid4().hex
        self.envelope: str | None = None
        self.payload: str | None = None
        self.diagnostic = ""

    @property
    def pending(self) -> bool:
        """Return whether this one-shot registration is still live.

        Returns:
            False after admission, disposal or failed delivery.
        """
        with self.dispatcher.lock:
            return self.id in self.dispatcher.tickets

    def cancel(self) -> None:
        """Revoke queued delivery and release logical interest, idempotently."""
        with self.dispatcher.lock:
            self.dispatcher.tickets.pop(self.id, None)
        self.settle()

    def complete(self, result: object, failure: Exception | None = None) -> None:
        """Encode an outcome while rich library values still remain in Python.

        Args:
            result: Original library return value, never retained by Kotlin.
            failure: Library failure, mapped explicitly or to its safe type name.
        """
        target = self.success if failure is None else self.failure
        if not self.pending:
            return
        if target is None:
            if failure is not None:
                self.diagnostic = f"extension work failed: {type(failure).__name__}"
                self.dispatcher.report(self.diagnostic)
            self.cancel()
            return
        try:
            values = (
                (self.encode(result) if self.encode else result)
                if failure is None
                else (
                    self.error(failure)
                    if self.error
                    else {"error": type(failure).__name__}
                )
            )
            payload = _payload(values, target)
            source = canonical_json(payload)
            with self.dispatcher.lock:
                if self.id not in self.dispatcher.tickets:
                    return
                self.payload = source
                self.envelope = canonical_json(
                    {"actionId": target.name, "payload": payload}
                )
            async_task.post(self.id, source)
        except Exception as exc:
            # Never serialize arbitrary exception messages, including mapper errors.
            self.diagnostic = f"extension outcome rejected: {type(exc).__name__}"
            self.dispatcher.report(self.diagnostic)
            self.cancel()


class Dispatcher:
    """A session epoch's completion registry and explicitly used resource owners."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.tickets: dict[str, Ticket] = {}
        self.resources: set[Any] = set()
        self.diagnostic = ""
        self.closed = False

    @contextmanager
    def active(self) -> Iterator[None]:
        """Bind outcome registration to the current worker transition.

        Yields:
            None: Registration is scoped to the worker context.
        """
        token = _current.set(self)
        try:
            yield
        finally:
            _current.reset(token)

    def register(self, ticket: Ticket) -> None:
        """Register before external work begins.

        Args:
            ticket: Completion to admit at most once in this epoch.

        Raises:
            StateError: If the session has already closed.
        """
        with self.lock:
            if self.closed:
                raise StateError("extension session is closed")
            self.tickets[ticket.id] = ticket

    def report(self, diagnostic: str) -> None:
        """Record bounded, payload-free diagnostic text.

        Args:
            diagnostic: Safe framework-authored category text.
        """
        with self.lock:
            self.diagnostic = diagnostic

    def resolve(self, source: str) -> str | None:
        """Admit a registered result on the worker immediately before dispatch.

        Args:
            source: Ordinary actionId/payload JSON from the existing host queue.

        Returns:
            The validated target envelope, unchanged ordinary input, or None for
            an obsolete/duplicate/tampered completion.
        """
        try:
            raw = json.loads(source, object_pairs_hook=_unique)
        except (ValueError, TypeError, RecursionError):
            return source  # Normal decoder owns malformed ordinary input.
        if not isinstance(raw, dict):
            return source
        identity = raw.get("actionId")
        if not isinstance(identity, str) or not identity.startswith(_PREFIX):
            return source
        with self.lock:
            ticket = self.tickets.pop(identity, None)
        if ticket is None:
            return None
        try:
            valid = (
                set(raw) == {"actionId", "payload"}
                and ticket.payload is not None
                and canonical_json(raw["payload"]) == ticket.payload
            )
            return ticket.envelope if valid else None
        finally:
            ticket.settle()

    def retire(self, successor: Dispatcher | None = None) -> None:
        """Retire an epoch; reload retains resources but never old completions.

        Args:
            successor: New epoch adopting live resources, or None to close them.
        """
        with self.lock:
            self.closed = True
            tickets, resources = tuple(self.tickets.values()), tuple(self.resources)
            self.tickets.clear()
            self.resources.clear()
        for ticket in tickets:
            ticket.settle()
        for resource in resources:
            resource._transfer(self, successor)
