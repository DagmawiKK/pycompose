"""Synchronous pull surface; the Android host owns the single Python worker."""

import logging
from threading import current_thread

from pycompose.bridge.types import decode_action
from pycompose.errors import BridgeError, SchemaError
from pycompose.ir import emit_ir, to_json, validate_ir
from pycompose.ir.generated_validators import SCHEMA_VERSION
from pycompose.state import Actions, State, Store

LOGGER = logging.getLogger(__name__)


def _unchanged(candidate: State, current: State) -> bool:
    if candidate is current:
        return True
    try:
        return candidate == current
    except RecursionError:
        # Node-owning State equality is recursive; emission still supports deep IR.
        return False


class BridgeSurface:
    """Process host actions before the host pulls the latest full snapshot."""

    def __init__(
        self,
        store: Store,
        actions: Actions,
        *,
        schema_version: str = SCHEMA_VERSION,
        debug: bool = True,
    ) -> None:
        """Bind the app state and handlers, and emit the initial snapshot.

        Args:
            store: Python-owned state store.
            actions: Registered pure transition handlers.
            schema_version: Wire schema version required by this host.
            debug: Strict IR validation and loud failure logging.

        Raises:
            SchemaError: If the configured schema or library version is incompatible.
        """
        self._store = store
        self._actions = actions
        self._schema_version = schema_version
        self._debug = debug
        self._worker = current_thread()
        self._processing = False
        self._latest: str | None = None
        try:
            self._latest = self._snapshot(store.value)
        except SchemaError:
            raise
        except Exception as exc:
            self._report("Initial snapshot unavailable", exc)

    def _require_worker(self) -> None:
        if current_thread() is not self._worker:
            raise BridgeError("bridge calls must run on the owning worker")

    def _require_idle_worker(self) -> None:
        self._require_worker()
        if self._processing:
            raise BridgeError("reentrant actions must be queued by the host worker")

    def _report(self, message: str, error: Exception) -> None:
        LOGGER.log(
            logging.ERROR if self._debug else logging.WARNING,
            "%s: %s",
            message,
            error,
            exc_info=self._debug,
        )

    def _snapshot(self, state: State) -> str | None:
        result = validate_ir(emit_ir(state, self._schema_version), debug=self._debug)
        for issue in result.issues:
            LOGGER.warning("IR validation: %s", issue)
        return to_json(result.snapshot) if result.snapshot is not None else None

    def accept_action(self, action_json: str) -> None:
        """Process one action synchronously; errors never escape to the host.

        Args:
            action_json: Registry-declared actionId and JSON payload.
        """
        try:
            self._require_idle_worker()
        except BridgeError as exc:
            self._report("Action ignored: worker contract violation", exc)
            return
        self._processing = True
        try:
            action = decode_action(action_json)
            current = self._store.value
            next_state = self._actions.dispatch(
                action.action_id, current, action.payload
            )
            if _unchanged(next_state, current):
                return
            snapshot = self._snapshot(next_state)
            if snapshot is not None:
                self._store.mutate(lambda _state: next_state)
                if snapshot != self._latest:
                    self._latest = snapshot
        except Exception as exc:
            self._report("Action ignored", exc)
        finally:
            self._processing = False

    def expose_latest_snapshot(self) -> str | None:
        """Return the latest canonical snapshot without consuming it.

        Returns:
            Canonical JSON or None if no valid snapshot exists.
        """
        try:
            self._require_worker()
        except BridgeError as exc:
            self._report("Snapshot unavailable: worker contract violation", exc)
            return None
        return self._latest
