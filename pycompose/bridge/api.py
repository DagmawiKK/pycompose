"""Synchronous pull surface; the Android host owns the single Python worker."""

from __future__ import annotations

import logging
from collections import deque
from threading import current_thread

from pycompose.bridge.types import decode_action
from pycompose.core.action_binding import BindingSpec, read_bindings
from pycompose.errors import BridgeError, SchemaError
from pycompose.extensions.delivery import Dispatcher
from pycompose.ir import IRRoot, emit_ir, to_json, validate_ir
from pycompose.ir.generated_validators import REGISTRY, SCHEMA_VERSION
from pycompose.ir.patch import ReplaceSubtree, diff_nodes, full_bytes, patch_bytes
from pycompose.state import Actions, State, Store

LOGGER = logging.getLogger(__name__)

PATCH_WINDOW = 4
"""Published roots kept for diffing (ADR-0018).

The host pulls after every action, so the root it holds is normally the one
published just before the latest. The window leaves room for a pull the host
dropped; a base older than this pulls the full snapshot instead.
"""


def _unchanged(candidate: State, current: State) -> bool:
    if candidate is current:
        return True
    try:
        return candidate == current
    except RecursionError:
        # Node-owning State equality is recursive; emission still supports deep IR.
        return False


class BridgeSurface:
    """Process host actions before the host pulls the latest snapshot."""

    def __init__(
        self,
        store: Store,
        actions: Actions,
        *,
        schema_version: str = SCHEMA_VERSION,
        debug: bool = True,
        first_serial: int = 1,
    ) -> None:
        """Bind the app state and handlers, and emit the initial snapshot.

        Args:
            store: Python-owned state store.
            actions: Registered pure transition handlers.
            schema_version: Wire schema version required by this host.
            debug: Strict IR validation and loud failure logging.
            first_serial: Serial of this surface's first published snapshot. A
                replacement surface continues its predecessor's numbering, so
                a base the host kept from before can never name its roots.

        Raises:
            BridgeError: If ``first_serial`` is not a positive integer.
            SchemaError: If the configured schema or library version is incompatible.
        """
        if isinstance(first_serial, bool) or first_serial < 1:
            raise BridgeError("first_serial must be a positive integer")
        self._store = store
        self._actions = actions
        self._schema_version = schema_version
        self._debug = debug
        self._worker = current_thread()
        self._processing = False
        self._latest: str | None = None
        self._latest_error = ""
        self._bindings: dict[str, BindingSpec] = {}
        self._deliveries = Dispatcher()
        self._serial = first_serial - 1
        self._published: deque[tuple[int, IRRoot]] = deque(maxlen=PATCH_WINDOW)
        try:
            text, root, self._bindings = self._snapshot(store.value)
        except SchemaError:
            raise
        except Exception as exc:
            self._report("Initial snapshot unavailable", exc)
        else:
            if text is not None and root is not None:
                self._publish(text, root)

    def _require_worker(self) -> None:
        if current_thread() is not self._worker:
            raise BridgeError("bridge calls must run on the owning worker")

    def _require_idle_worker(self) -> None:
        self._require_worker()
        if self._processing:
            raise BridgeError("reentrant actions must be queued by the host worker")

    def _report(self, message: str, error: Exception) -> None:
        self._latest_error = f"{message}: {error}"
        LOGGER.log(
            logging.ERROR if self._debug else logging.WARNING,
            "%s: %s",
            message,
            error,
            exc_info=self._debug,
        )

    def _snapshot(
        self, state: State
    ) -> tuple[str | None, IRRoot | None, dict[str, BindingSpec]]:
        result = validate_ir(emit_ir(state, self._schema_version), debug=self._debug)
        for issue in result.issues:
            LOGGER.warning("IR validation: %s", issue)
        if result.snapshot is None:
            return None, None, {}
        bindings = read_bindings(result.snapshot.metadata)
        self._actions.validate_bindings(bindings)
        return to_json(result.snapshot), result.snapshot, bindings

    def _publish(self, text: str, root: IRRoot) -> None:
        """Make a validated snapshot the latest, numbering it when it differs.

        Args:
            text: The snapshot's canonical JSON.
            root: The validated snapshot that JSON encodes.
        """
        if text == self._latest:
            return
        self._latest = text
        self._serial += 1
        self._published.append((self._serial, root))

    def _kept(self, serial: int) -> IRRoot | None:
        if isinstance(serial, bool) or not isinstance(serial, int):
            return None
        return next((root for kept, root in self._published if kept == serial), None)

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
        self._latest_error = ""
        try:
            if self._deliveries.closed:
                return
            admitted = self._deliveries.resolve(action_json)
            if admitted is None:
                return
            action = decode_action(
                admitted,
                bindings=self._bindings,
                handlers=self._actions,
            )
            if (
                action.action_id in REGISTRY.lifecycle
                and action.action_id not in self._actions
            ):
                # The host reports every lifecycle fact unconditionally, so
                # whether one has a handler is the app's choice; an event
                # nobody opted into is idle, not a fault worth a diagnostic.
                LOGGER.debug("lifecycle event has no handler: %s", action.action_id)
                return
            current = self._store.value
            with self._deliveries.active():
                next_state = (
                    self._actions.dispatch_binding(
                        action.binding, current, action.payload
                    )
                    if action.binding is not None
                    else self._actions.dispatch(
                        action.action_id,
                        current,
                        action.payload,
                    )
                )
            if _unchanged(next_state, current):
                return
            text, root, bindings = self._snapshot(next_state)
            if text is not None and root is not None:
                self._store.mutate(lambda _state: next_state)
                self._bindings = bindings
                self._publish(text, root)
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

    @property
    def serial(self) -> int:
        """Serial of the latest published snapshot.

        Returns:
            The latest serial, or ``first_serial - 1`` before any snapshot.
        """
        return self._serial

    def expose_latest_envelope(self, base_serial: int) -> str | None:
        """Return the latest snapshot as a pull envelope against the host's base.

        ADR-0018: a host that still holds a recently published snapshot gets a
        ``patch`` envelope of ops against it; any other host gets the ``full``
        snapshot. A diff that replaces the root would ship the whole tree plus
        envelope fields, so that case ships ``full`` instead. Pulling the
        latest serial itself yields a patch with no ops.

        Args:
            base_serial: Serial of the snapshot the host holds. Any serial this
                surface no longer keeps, such as 0 before the host's first pull,
                selects the full snapshot.

        Returns:
            Canonical envelope JSON, or None if no valid snapshot exists.
        """
        try:
            self._require_worker()
        except BridgeError as exc:
            self._report("Snapshot unavailable: worker contract violation", exc)
            return None
        if not self._published:
            return None
        serial, latest = self._published[-1]
        base = self._kept(base_serial)
        if base is not None:
            try:
                ops = diff_nodes(base.root, latest.root)
                if not any(
                    isinstance(op, ReplaceSubtree) and op.id == latest.root.id
                    for op in ops
                ):
                    return patch_bytes(
                        latest, ops, base_serial=base_serial, serial=serial
                    ).decode()
            except Exception as exc:
                self._report("Patch unavailable; sending the full snapshot", exc)
        return full_bytes(latest, serial=serial).decode()

    def expose_latest_error(self) -> str:
        """Return the latest worker diagnostic as plain data.

        Returns:
            Error text, or an empty string for a successful transition.
        """
        self._require_worker()
        return self._latest_error or self._deliveries.diagnostic

    def close(self, *, successor: BridgeSurface | None = None) -> None:
        """Retire completion registrations and clean up or transfer used resources.

        Args:
            successor: Replacement after successful reload, or None on shutdown.
        """
        self._require_worker()
        self._deliveries.retire(
            successor._deliveries if successor is not None else None
        )
