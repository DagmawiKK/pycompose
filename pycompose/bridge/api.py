"""Synchronous pull surface; the Android host owns the single Python worker."""

from __future__ import annotations

import itertools
import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from threading import current_thread
from typing import Protocol

from pycompose.app.observe import Span
from pycompose.bridge.stats import PassStats
from pycompose.bridge.types import MAIN_SURFACE, Action, decode_action
from pycompose.contract.catalog import REGISTRY, SCHEMA_VERSION
from pycompose.contract.registry_types import PropDef
from pycompose.contract.version import at_least
from pycompose.core.action_binding import BindingSpec, read_intents
from pycompose.core.expansion import ExpansionMemo
from pycompose.core.ids import Handles
from pycompose.core.reuse import Reuse
from pycompose.core.windows import windows
from pycompose.errors import BridgeError, SchemaError
from pycompose.ir import emit_ir, to_json, validate_ir
from pycompose.ir.echoes import ECHOES_SCHEMA, echo_key
from pycompose.ir.host import Host, hosted
from pycompose.ir.model import IRRoot
from pycompose.ir.patch import ReplaceSubtree, diff_nodes, full_bytes, patch_bytes
from pycompose.runtime.trace import tracing
from pycompose.state import State, Store

LOGGER = logging.getLogger(__name__)

VERIFY_EVERY = 0
"""Every n-th reused composable is expanded again and compared; 0 never.

Debug and release behave the same, so neither pays for it; tests set it to 1
and catch an impure composable on its first reuse."""

WINDOW = 8
"""Published snapshots kept as patch bases for a host that is behind."""

PASS_BUDGET = 0.1
"""Seconds one action may take before debug reports it; taps behind it wait."""

MAX_PATCH_OPS = 64
"""Beyond this many ops, a whole snapshot is cheaper to send and to apply."""

_SERIALS = itertools.count(1)
"""Process-wide, so a serial never names another session's snapshot."""


class AppSession(Protocol):
    """What the bridge asks of the app it serves: the back stack's interface."""

    def validate_intents(
        self, intents: Mapping[str, Mapping[str, PropDef]]
    ) -> None: ...  # pragma: no cover - protocol declaration

    def contract(
        self, action_id: str
    ) -> Mapping[str, PropDef] | None: ...  # pragma: no cover - protocol declaration

    def __contains__(
        self, action_id: object
    ) -> bool: ...  # pragma: no cover - protocol declaration

    def declared(
        self, action_id: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]: ...  # pragma: no cover - protocol declaration

    def dispatch(
        self, action_id: str, state: State, payload: Mapping[str, object]
    ) -> State: ...  # pragma: no cover - protocol declaration

    def dispatch_binding(
        self, spec: BindingSpec, state: State, payload: Mapping[str, object]
    ) -> State: ...  # pragma: no cover - protocol declaration

    def close(self) -> None: ...  # pragma: no cover - protocol declaration


def _echo_target(key: str) -> str:
    """Return the handler or registry action an echo key names."""
    target = json.loads(key)
    return str(target["intent"]) if isinstance(target, dict) else str(target)


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
        session: AppSession,
        *,
        schema_version: str = SCHEMA_VERSION,
        debug: bool = True,
        host_components: frozenset[str] | None = None,
        on_pass: Callable[[Span], None] | None = None,
    ) -> None:
        """Bind the app state and session, and emit the initial snapshot.

        Args:
            store: Python-owned state store.
            session: The app's back stack, which handles every action.
            schema_version: Wire schema version required by this host.
            debug: Strict IR validation and loud failure logging.
            host_components: The component types the host's handshake offered;
                None when it listed none.
            on_pass: Receives one span per action pass, in release as in debug.

        Raises:
            SchemaError: If the configured schema or library version is incompatible.
        """
        self._store = store
        self._session = session
        self._closed = False
        self._stats = PassStats(on_pass)
        self._schema_version = schema_version
        self._debug = debug
        self._host = Host(host_components, schema_version)
        self._announced: set[str] = set()
        self._worker = current_thread()
        self._processing = False
        self._latest: str | None = None
        # Each snapshot a host may still hold, as a base for its next patch.
        self._published: list[tuple[int, IRRoot]] = []
        self._latest_error = ""
        self._pass: dict[str, float] = {}
        # Phases summed over every action since the host last read them: one
        # host pass may run several actions before it pulls.
        self._batch: dict[str, float] = {}
        # The handlers the latest snapshot states, whose echoes are kept.
        self._intents: frozenset[str] = frozenset()
        # The latest report sequence number answered, per action (plan 31 §17).
        self._echoes: dict[str, int] = {}
        # The window the host last asked for, per lazy container key.
        self._windows: dict[str, tuple[int, int]] = {}
        # Both name nodes compactly; debug also keeps the readable paths.
        self._reuse = Reuse(
            ExpansionMemo(verify_every=VERIFY_EVERY),
            handles=Handles(readable=debug),
        )
        try:
            root, text, intents = self._snapshot(store.value)
            self._intents = frozenset(intents)
            self._publish(root, text)
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
    ) -> tuple[IRRoot, str, dict[str, Mapping[str, PropDef]]]:
        echoes = self._echoes if at_least(self._schema_version, ECHOES_SCHEMA) else None
        with hosted(self._host):
            with windows(self._windows), self._timed("view"):
                emitted = emit_ir(
                    state, self._schema_version, self._reuse, echoes=echoes
                )
            with self._timed("validate"):
                # Debug checks here and refuses an invalid snapshot; release
                # leaves the one check to the host's typed parse, which refuses
                # it the same way, keeping the last good snapshot on screen.
                intents = (
                    dict(validate_ir(emitted, reuse=self._reuse).intents)
                    if self._debug
                    else dict(read_intents(emitted.metadata))
                )
        if self._debug:
            for reason in self._reuse.expansion.reasons:
                LOGGER.debug("Rebuilt %s", reason)
            for missing in sorted(self._host.substituted - self._announced):
                LOGGER.warning("The host has no %s; showing its fallback", missing)
            self._announced |= self._host.substituted
        self._session.validate_intents(intents)
        with self._timed("serialize"):
            text = to_json(emitted, self._reuse)
        return emitted, text, intents

    @contextmanager
    def _timed(self, phase: str) -> Iterator[None]:
        """Add the time spent inside to this pass's ``phase``, in milliseconds."""
        started = time.perf_counter()
        try:
            yield
        finally:
            spent = (time.perf_counter() - started) * 1000
            self._pass[phase] = self._pass.get(phase, 0.0) + spent

    def _publish(self, root: IRRoot, text: str) -> None:
        if text == self._latest:
            return
        self._stats.counts["published"] += 1
        self._latest = text
        entry = (next(_SERIALS), root)
        self._published = [*self._published[1 - WINDOW :], entry]

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
        self._pass = {}
        started = time.perf_counter()
        current = self._store.value
        echoed = False
        name, trace, failed = "", None, False
        try:
            if self._closed:
                return
            action = decode_action(
                action_json,
                contracts=self._session.contract,
                handlers=self._session,
            )
            name, trace = action.action_id, action.trace
            if action.seq is not None:
                # Answered even when the handler changes nothing or fails: the
                # host waits for this echo before it drives the holder again.
                self._echoes[echo_key(action.target)] = action.seq
                echoed = True
            with tracing(trace):
                if self._apply(action, current, echoed=echoed):
                    echoed = False
        except Exception as exc:
            failed = True
            self._report("Action ignored", exc)
        finally:
            if echoed:
                self._republish(current)
            self._processing = False
            elapsed = time.perf_counter() - started
            self._stats.record(name, trace, elapsed * 1000, self._pass, failed=failed)
            # One host pass may run several actions before it pulls; its log
            # line reads them all, plus the time spent inside the actions.
            for phase, ms in (
                *self._pass.items(),
                ("actions", 1.0),
                ("accept", elapsed * 1000),
            ):
                self._batch[phase] = self._batch.get(phase, 0.0) + ms
            if self._debug and elapsed > PASS_BUDGET:
                LOGGER.warning(
                    "Action pass took %.0f ms, over the %.0f ms budget; every tap "
                    "behind it waited",
                    elapsed * 1000,
                    PASS_BUDGET * 1000,
                )

    def _apply(self, action: Action, current: State, *, echoed: bool) -> bool:
        """Run one decoded action and publish what it changed.

        Args:
            action: The decoded action.
            current: The state before it.
            echoed: Whether the action carries an echo still to publish.

        Returns:
            Whether a snapshot was published, echo included.
        """
        if (
            action.action_id in REGISTRY.lifecycle
            and action.action_id not in self._session
        ):
            # The host reports every lifecycle fact unconditionally, so
            # whether one has a handler is the app's choice; an event
            # nobody opted into is idle, not a fault worth a diagnostic.
            LOGGER.debug("lifecycle event has no handler: %s", action.action_id)
            return False
        with self._timed("handler"):
            next_state = (
                self._session.dispatch_binding(action.binding, current, action.payload)
                if action.binding is not None
                else self._session.dispatch(
                    action.action_id,
                    current,
                    self._host_fields(action.action_id, action.payload),
                )
            )
        if _unchanged(next_state, current) and not echoed:
            return False
        self._publish_state(next_state)
        return True

    def counters(self) -> dict[str, object]:
        """Return release-safe counts of passes, publications and failures.

        Returns:
            Counts, the longest pass and total milliseconds by phase.
        """
        self._require_worker()
        return self._stats.snapshot()

    def _publish_state(self, state: State) -> None:
        """Publish ``state`` and make it the store's; an invalid one raises first.

        Args:
            state: The state to render.
        """
        root, text, intents = self._snapshot(state)
        self._store.mutate(lambda _state: state)
        self._intents = frozenset(intents)
        self._publish(root, text)

    def _republish(self, state: State) -> None:
        """Publish the unchanged ``state`` again so it carries the latest echoes.

        Args:
            state: The state the store already holds.
        """
        self._echoes = {
            key: seq
            for key, seq in self._echoes.items()
            if _echo_target(key) in self._intents
            or _echo_target(key) in REGISTRY.actions
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
            return self._session.declared(action_id, payload)
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
        serial, latest = self._published[-1]
        base = next((root for s, root in self._published if s == base_serial), None)
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

    def expose_last_pass(self) -> str:
        """Return the time by phase of every action since the last call.

        Returns:
            JSON milliseconds by phase (handler, view, validate, serialize),
            ``accept`` for the whole of the actions and ``actions`` for how many.
        """
        self._require_worker()
        batch, self._batch = self._batch, {}
        return json.dumps({k: round(v, 2) for k, v in batch.items()})

    def node_paths(self) -> dict[str, str]:
        """Return each node name's readable path, kept only in debug.

        Returns:
            Readable path by node id; empty in release.
        """
        self._require_worker()
        return self._reuse.handles.paths()

    def expose_latest_error(self) -> str:
        """Return the latest worker diagnostic as plain data.

        Returns:
            Error text, or an empty string for a successful transition.
        """
        self._require_worker()
        return self._latest_error

    def close(self) -> None:
        """End the session: its view models are cleared and later actions ignored."""
        self._require_worker()
        self._closed = True
        self._session.close()
