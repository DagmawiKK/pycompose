"""Synchronous pull surface; the Android host owns the single Python worker."""

from __future__ import annotations

import itertools
import logging
import time
from collections.abc import Mapping
from threading import current_thread

from pycompose import async_task  # noqa: F401 -- installs the async action runner
from pycompose.bridge.types import MAIN_SURFACE, decode_action
from pycompose.core.action_binding import BindingSpec
from pycompose.core.expansion import ExpansionMemo
from pycompose.core.ids import Handles
from pycompose.core.reuse import Reuse
from pycompose.core.windows import windows
from pycompose.errors import BridgeError, SchemaError
from pycompose.extensions.delivery import Dispatcher
from pycompose.ir import emit_ir, to_json, validate_ir
from pycompose.ir.echoes import ECHOES_SCHEMA
from pycompose.ir.generated_validators import REGISTRY, SCHEMA_VERSION
from pycompose.ir.host import Host, hosted
from pycompose.ir.model import IRRoot
from pycompose.ir.patch import ReplaceSubtree, diff_nodes, full_bytes, patch_bytes
from pycompose.schema.version import at_least
from pycompose.state import Actions, State, Store

LOGGER = logging.getLogger(__name__)

VERIFY_EVERY = 8
"""In debug, every n-th reused composable is expanded again and compared."""

WINDOW = 8
"""Published snapshots kept as patch bases for a host that is behind."""

PASS_BUDGET = 0.1
"""Seconds one action may take before debug reports it; taps behind it wait."""

MAX_PATCH_OPS = 64
"""Beyond this many ops, a whole snapshot is cheaper to send and to apply."""

_SERIALS = itertools.count(1)
"""Process-wide, so a serial never names another session's snapshot."""


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
        host_components: frozenset[str] | None = None,
    ) -> None:
        """Bind the app state and handlers, and emit the initial snapshot.

        Args:
            store: Python-owned state store.
            actions: Registered pure transition handlers.
            schema_version: Wire schema version required by this host.
            debug: Strict IR validation and loud failure logging.
            host_components: The component types the host's handshake offered;
                None when it listed none.

        Raises:
            SchemaError: If the configured schema or library version is incompatible.
        """
        self._store = store
        self._actions = actions
        self._schema_version = schema_version
        self._debug = debug
        self._host = Host(host_components, schema_version)
        self._announced: set[str] = set()
        self._worker = current_thread()
        self._processing = False
        self._latest: str | None = None
        # Each snapshot a host may still hold, with the bindings it carried.
        self._published: list[tuple[int, IRRoot, dict[str, BindingSpec]]] = []
        self._latest_error = ""
        self._bindings: dict[str, BindingSpec] = {}
        # The latest report sequence number answered, per action (plan 31 §17).
        self._echoes: dict[str, int] = {}
        # The window the host last asked for, per lazy container key.
        self._windows: dict[str, tuple[int, int]] = {}
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
                self._publish(published[0], published[1], published[2])
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
        with hosted(self._host):
            with windows(self._windows):
                emitted = emit_ir(
                    state, self._schema_version, self._reuse, echoes=echoes
                )
            result = validate_ir(emitted, debug=self._debug, reuse=self._reuse)
        if self._debug:
            for reason in self._reuse.expansion.reasons:
                LOGGER.debug("Rebuilt %s", reason)
            for missing in sorted(self._host.substituted - self._announced):
                LOGGER.warning("The host has no %s; showing its fallback", missing)
            self._announced |= self._host.substituted
        for issue in result.issues:
            LOGGER.warning("IR validation: %s", issue)
        if result.snapshot is None:
            return None
        bindings = dict(result.bindings)
        self._actions.validate_bindings(bindings)
        return result.snapshot, to_json(result.snapshot, self._reuse), bindings

    def _publish(
        self, root: IRRoot, text: str, bindings: dict[str, BindingSpec]
    ) -> None:
        if text == self._latest:
            return
        self._latest = text
        entry = (next(_SERIALS), root, bindings)
        self._published = [*self._published[1 - WINDOW :], entry]

    def _bindings_at(self, serial: int | None) -> Mapping[str, BindingSpec] | None:
        """Return the bindings of the snapshot the host acted on.

        A tap resolves against what the user saw: a binding whose id survives
        into a later snapshot may carry different bound values there.

        Args:
            serial: The snapshot the action was dispatched against; None for
                actions that name none.

        Returns:
            Its bindings, or None when that snapshot is no longer held.
        """
        if serial is None:
            return self._bindings
        return next((b for s, _, b in self._published if s == serial), None)

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
        started = time.perf_counter()
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
                bindings=self._bindings_at,
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
                        self._host_fields(action.action_id, action.payload),
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
            elapsed = time.perf_counter() - started
            if self._debug and elapsed > PASS_BUDGET:
                LOGGER.warning(
                    "Action pass took %.0f ms, over the %.0f ms budget; every tap "
                    "behind it waited",
                    elapsed * 1000,
                    PASS_BUDGET * 1000,
                )

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
        self._publish(published[0], published[1], published[2])
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

    def _host_fields(
        self, action_id: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        """Pass a host event's handler only the fields it declares.

        Args:
            action_id: The event's id.
            payload: Its fields, already checked against the host contract.

        Returns:
            The fields the handler reads, for a host-declared event; the
            payload unchanged for an app handler addressed by name.
        """
        if action_id in REGISTRY.lifecycle or action_id in REGISTRY.actions:
            return self._actions.declared(action_id, payload)
        return payload

    def request_window(
        self, key: str, first: int, last: int, surface: str = MAIN_SURFACE
    ) -> None:
        """Compose the window of a lazy container the host now shows.

        Args:
            key: The container's window key, as its snapshot stated it.
            first: The first item index wanted.
            last: The last item index wanted.
            surface: The surface showing the container.
        """
        try:
            self._require_idle_worker()
        except BridgeError as exc:
            self._report("Window ignored: worker contract violation", exc)
            return
        if surface != MAIN_SURFACE or first < 0 or last < first:
            self._report("Window ignored", BridgeError("invalid window", key=key))
            return
        if self._windows.get(key) == (first, last):
            return
        self._windows[key] = (first, last)
        try:
            self._publish_state(self._store.value)
        except Exception as exc:
            self._report("Window unavailable", exc)

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

    def expose_envelope(self, base_serial: int, surface: str = MAIN_SURFACE) -> str:
        """Return the latest snapshot as a patch against the host's base, or whole.

        A base still in the window gets the ops that turn it into the latest
        snapshot (ADR-0018); an unknown, stale or other session's base, a
        replaced root, or a change past MAX_PATCH_OPS gets the whole snapshot.

        Args:
            base_serial: The serial of the snapshot the host holds; -1 for none.
            surface: The surface being pulled; a session hosts only the main one.

        Returns:
            The envelope as canonical JSON, or empty before any valid snapshot.
        """
        try:
            self._require_worker()
        except BridgeError as exc:
            self._report("Snapshot unavailable: worker contract violation", exc)
            return ""
        if surface != MAIN_SURFACE:
            unknown = BridgeError("unknown surface", surface=surface)
            self._report("Snapshot unavailable", unknown)
            return ""
        if not self._published:
            return ""
        serial, latest, _ = self._published[-1]
        base = next((root for s, root, _ in self._published if s == base_serial), None)
        if base is not None:
            ops = diff_nodes(base.root, latest.root)
            whole = any(
                isinstance(op, ReplaceSubtree) and op.id == latest.root.id for op in ops
            )
            if len(ops) <= MAX_PATCH_OPS and not whole:
                envelope = patch_bytes(
                    latest,
                    ops,
                    base_serial=base_serial,
                    serial=serial,
                    surface=surface,
                    base=base,
                )
                return envelope.decode("utf-8")
        full = full_bytes(latest, serial=serial, surface=surface, reuse=self._reuse)
        return full.decode("utf-8")

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
