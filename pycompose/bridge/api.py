"""Synchronous pull surface; the Android host owns the single Python worker."""

from __future__ import annotations

import itertools
import logging
from threading import current_thread

from pycompose.bridge.types import decode_action
from pycompose.core.action_binding import BindingSpec
from pycompose.core.expansion import ExpansionMemo
from pycompose.core.ids import Handles
from pycompose.core.reuse import Reuse
from pycompose.errors import BridgeError, SchemaError
from pycompose.extensions.delivery import Dispatcher
from pycompose.ir import emit_ir, to_json, validate_ir
from pycompose.ir.generated_validators import REGISTRY, SCHEMA_VERSION
from pycompose.ir.model import IRRoot
from pycompose.ir.patch import ReplaceSubtree, diff_nodes, full_bytes, patch_bytes
from pycompose.schema.version import at_least
from pycompose.state import Actions, State, Store

LOGGER = logging.getLogger(__name__)

VERIFY_EVERY = 8
"""In debug, every n-th reused composable is expanded again and compared."""

WINDOW = 8
"""Published snapshots kept as patch bases for a host that is behind."""

MAX_PATCH_OPS = 64
"""Beyond this many ops, a whole snapshot is cheaper to send and to apply."""

_SERIALS = itertools.count(1)
"""Process-wide, so a serial never names another session's snapshot."""

ECHOES_SCHEMA = "1.23.0"
"""First schema whose snapshots echo the host's report sequence numbers."""


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
        self._published: list[tuple[int, IRRoot]] = []
        self._latest_error = ""
        self._bindings: dict[str, BindingSpec] = {}
        # The latest report sequence number answered, per action (plan 31 §17).
        self._echoes: dict[str, int] = {}
        self._deliveries = Dispatcher()
        # Debug re-expands a sample of reused composables to catch impure ones,
        # and names nodes by readable paths; release names them compactly.
        self._reuse = Reuse(
            ExpansionMemo(verify_every=VERIFY_EVERY if debug else 0),
            handles=Handles(compact=not debug),
        )
        try:
            published = self._snapshot(store.value)
            if published is not None:
                self._bindings = published[2]
                self._publish(published[0], published[1])
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
    ) -> tuple[IRRoot, str, dict[str, BindingSpec]] | None:
        echoes = self._echoes if at_least(self._schema_version, ECHOES_SCHEMA) else None
        emitted = emit_ir(state, self._schema_version, self._reuse, echoes=echoes)
        result = validate_ir(emitted, debug=self._debug, reuse=self._reuse)
        for issue in result.issues:
            LOGGER.warning("IR validation: %s", issue)
        if result.snapshot is None:
            return None
        bindings = dict(result.bindings)
        self._actions.validate_bindings(bindings)
        return result.snapshot, to_json(result.snapshot, self._reuse), bindings

    def _publish(self, root: IRRoot, text: str) -> None:
        if text == self._latest:
            return
        self._latest = text
        self._published = [*self._published[1 - WINDOW :], (next(_SERIALS), root)]

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
        current = self._store.value
        echoed = False
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
            if action.seq is not None:
                # Answered even when the handler changes nothing or fails: the
                # host waits for this echo before it drives the holder again.
                self._echoes[action.action_id] = action.seq
                echoed = True
            if (
                action.action_id in REGISTRY.lifecycle
                and action.action_id not in self._actions
            ):
                # The host reports every lifecycle fact unconditionally, so
                # whether one has a handler is the app's choice; an event
                # nobody opted into is idle, not a fault worth a diagnostic.
                LOGGER.debug("lifecycle event has no handler: %s", action.action_id)
                return
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
            if _unchanged(next_state, current) and not echoed:
                return
            if self._publish_state(next_state):
                echoed = False
        except Exception as exc:
            self._report("Action ignored", exc)
        finally:
            if echoed:
                self._republish(current)
            self._processing = False

    def _publish_state(self, state: State) -> bool:
        """Publish ``state`` and make it the store's; False when it is invalid.

        Args:
            state: The state to render.

        Returns:
            Whether a snapshot was published.
        """
        published = self._snapshot(state)
        if published is None:
            return False
        self._store.mutate(lambda _state: state)
        self._bindings = published[2]
        self._publish(published[0], published[1])
        return True

    def _republish(self, state: State) -> None:
        """Publish the unchanged ``state`` again so it carries the latest echoes.

        Args:
            state: The state the store already holds.
        """
        self._echoes = {
            key: seq
            for key, seq in self._echoes.items()
            if key in self._bindings or key in REGISTRY.actions
        }
        try:
            self._publish_state(state)
        except Exception as exc:
            self._report("Echo unavailable", exc)

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

    def expose_envelope(self, base_serial: int) -> str:
        """Return the latest snapshot as a patch against the host's base, or whole.

        A base still in the window gets the ops that turn it into the latest
        snapshot (ADR-0018); an unknown, stale or other session's base, a
        replaced root, or a change past MAX_PATCH_OPS gets the whole snapshot.

        Args:
            base_serial: The serial of the snapshot the host holds; -1 for none.

        Returns:
            The envelope as canonical JSON, or empty before any valid snapshot.
        """
        try:
            self._require_worker()
        except BridgeError as exc:
            self._report("Snapshot unavailable: worker contract violation", exc)
            return ""
        if not self._published:
            return ""
        serial, latest = self._published[-1]
        base = next((root for s, root in self._published if s == base_serial), None)
        if base is not None:
            ops = diff_nodes(base.root, latest.root)
            whole = any(
                isinstance(op, ReplaceSubtree) and op.id == latest.root.id for op in ops
            )
            if len(ops) <= MAX_PATCH_OPS and not whole:
                envelope = patch_bytes(
                    latest, ops, base_serial=base_serial, serial=serial, base=base
                )
                return envelope.decode("utf-8")
        return full_bytes(latest, serial=serial, reuse=self._reuse).decode("utf-8")

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
