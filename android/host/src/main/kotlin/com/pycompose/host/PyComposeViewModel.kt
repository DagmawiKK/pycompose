package com.pycompose.host

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import com.pycompose.host.bridge.BridgeSurface
import com.pycompose.ir.AppBindings
import com.pycompose.ir.AppData
import com.pycompose.ir.EffectRequest
import com.pycompose.ir.Effects
import com.pycompose.ir.Lifecycle
import com.pycompose.ir.SnapshotStream
import com.pycompose.ir.ValidatedIr
import com.pycompose.renderer.Action
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject

/**
 * An accepted snapshot paired atomically with its native session lifetime.
 *
 * @param ir Validated wire data to render.
 * @param epoch Host-local generation, retained on rotation and advanced on Python restart.
 * @param traces The spans of the commands that produced it, closed by the frame that shows it.
 * @param serial The serial the app published it under; actions taken on it name it.
 * @param timing Its pass's time by stage, logged when its frame is drawn; null unless timed.
 */
data class SessionSnapshot(
    val ir: ValidatedIr,
    val epoch: Long,
    val traces: List<Int> = emptyList(),
    val serial: Long = SnapshotStream.NONE,
    val timing: PassTiming? = null,
)

/**
 * Host owns only latest IR and minimal navigation state, never the Python Store.
 *
 * It is the one object between the activity and the Python worker: its public calls
 * queue commands, and its private ones run them on the worker. Splitting the two halves
 * would put the worker's queue and its consumer in different types, so it sits just
 * over detekt's default function count.
 */
@Suppress("TooManyFunctions")
class PyComposeViewModel(
    private val bridge: BridgeSurface,
    private val savedState: SavedStateHandle,
    dispatcher: CoroutineDispatcher,
    initialConfig: JsonObject? = null,
    private val timePasses: Boolean = false,
) : ViewModel() {
    /** Set by the activity; when attached, any queued effects are immediately drained. */
    var effectRunner: EffectRunner? = null
        set(value) {
            field = value
            if (value != null && pendingEffects.isNotEmpty()) {
                val toRun = pendingEffects.toList()
                pendingEffects.clear()
                value.runAll(toRun)
            }
        }
    private val pendingEffects = mutableListOf<EffectRequest>()
    private val scope = CoroutineScope(SupervisorJob() + dispatcher)
    private val commands = Channel<Queued>(QUEUE_CAPACITY)
    private val stream = SnapshotStream()
    private val mutableSnapshot = MutableStateFlow<SessionSnapshot?>(null)
    private val mutableError = MutableStateFlow("")
    val snapshot: StateFlow<SessionSnapshot?> = mutableSnapshot.asStateFlow()
    val error: StateFlow<String> = mutableError.asStateFlow()
    private var route = savedState.get<String>("route") ?: "home"
    private var restore = savedState.get<String>(STATE) ?: ""
    private var epoch = (savedState.get<Long>(EPOCH) ?: -1L) + 1L
    private val resultSubscription: AutoCloseable
    private val admissionSubscription: AutoCloseable
    private val outcomeAdmission =
        OutcomeAdmission(
            accept = { enqueue(Command.Push(it)) },
            rejected = { mutableError.value = "Async result rejected" },
        )

    init {
        savedState[EPOCH] = epoch
        initialConfig?.let { Lifecycle.check("onConfigChanged", it) }
        // Background Python results arrive from any thread and are queued here, so
        // the worker still only ever sees them as ordinary actions.
        resultSubscription =
            AsyncResult.listen { actionId, payload ->
                outcomeAdmission.offer(actionId, payload)
            }
        admissionSubscription = AsyncResult.listenAdmission(outcomeAdmission::offer)
        val restored = route
        val saved = restore
        scope.launch {
            try {
                perform(listOf(ActionTrace.begin()), System.nanoTime()) {
                    bridge.start(restored, saved)
                    // Facts Python cannot observe itself (appearance, size, locale) must
                    // reach it before the first pull: the pull is the frame the user
                    // sees, and an app that paints from these facts would otherwise
                    // render its default palette and flash when the report lands late.
                    initialConfig?.let { config ->
                        bridge.acceptAction(Action("onConfigChanged", config).toJson())
                    }
                    true
                }
                for (first in commands) {
                    // Everything queued behind the first command runs before one
                    // pull: a burst costs one snapshot, not one per command.
                    val batch =
                        coalesce(
                            listOf(first) + generateSequence { commands.tryReceive().getOrNull() },
                        )
                    perform(batch.map { it.cookie }, batch.minOf { it.queuedAt }) {
                        batch.map { run(it.command) }.any { it }
                    }
                }
            } finally {
                // Cancellation runs this synchronous teardown on the owning worker.
                // Python retires interest now and closes resources on their own lanes.
                runCatching { bridge.close() }
                    .onFailure { mutableError.value = "Python cleanup failed" }
            }
        }
    }

    /**
     * Deliver one command; its failure is reported and the rest of the batch still runs.
     *
     * @return Whether it reached Python, so there may be a new snapshot to pull.
     */
    @Suppress("TooGenericExceptionCaught")
    private fun run(command: Command): Boolean {
        try {
            when (command) {
                is Command.Dispatch -> {
                    val source = command.action.toJson()
                    val current =
                        checkNotNull(mutableSnapshot.value) { "No active snapshot" }
                    AppBindings.validateAction(source, current.ir).getOrThrow()
                    bridge.acceptAction(source)
                }
                is Command.Lifecycle -> {
                    // Platform events validate against the lifecycle
                    // contract alone: no snapshot has to exist yet.
                    Lifecycle.check(command.event, command.payload)
                    bridge.acceptAction(command.action.toJson())
                }
                is Command.Reload -> {
                    if (bridge.reload(command.route, restore)) {
                        // A new Python session knows no serial the host holds.
                        stream.reset()
                        epoch += 1
                        savedState[EPOCH] = epoch
                    }
                }
                is Command.Navigate -> {
                    // A route change is an ordinary inbound action, not a
                    // reason to rebuild Python. Restarting here would
                    // discard the app's session on every navigation, which
                    // is what makes a ViewModel impossible to retain.
                    Lifecycle.check("onRouteChanged", command.action.payload)
                    bridge.acceptAction(command.action.toJson())
                }
                is Command.Window ->
                    bridge.requestWindow(stream.surface, command.key, command.first, command.last)
                is Command.Push -> {
                    // A background result, delivered exactly as a tap would
                    // be: the payload is the app's, and its handler's
                    // declared contract is what checks it.
                    bridge.acceptAction(command.action.toJson())
                }
            }
            return true
        } catch (failure: Exception) {
            mutableError.value = failure.message ?: "Python worker failure"
            return false
        }
    }

    /** Report one host lifecycle event to Python as a plain action envelope. */
    fun lifecycle(
        event: String,
        payload: JsonObject = JsonObject(emptyMap()),
    ) {
        require(event in Lifecycle.ids) { "Undeclared lifecycle event: $event" }
        enqueue(Command.Lifecycle(event, payload))
    }

    fun dispatch(action: Action) {
        // Stamped with what was on screen when the user acted, not when it is processed.
        val shown = mutableSnapshot.value?.serial?.takeIf { it != SnapshotStream.NONE }
        enqueue(Command.Dispatch(action.copy(serial = shown)))
    }

    /** Ask Python for items [first] to [last] of the lazy list keyed [key]. */
    fun requestWindow(
        key: String,
        first: Int,
        last: Int,
    ) {
        enqueue(Command.Window(key, first, last))
    }

    fun reload() {
        enqueue(Command.Reload(route))
    }

    /**
     * Move the app to [destination] by telling Python, not by restarting it.
     *
     * Python stays the single source of truth for what is on screen, so the new
     * route is echoed back to it as an ordinary lifecycle action and Python decides
     * what that route means. The host keeps the string only so it can restore the
     * same screen after process death. Called from the UI thread.
     */
    fun navigate(destination: String) {
        require(destination.isNotBlank())
        route = destination
        savedState["route"] = destination
        enqueue(Command.Navigate(destination))
    }

    /** Execute the effects this snapshot asked for, at most once per snapshot. */
    private fun runEffects(ir: ValidatedIr) {
        val requested = Effects.read(ir.snapshot.metadata, ir.snapshot.schemaVersion)
        if (requested.isNotEmpty()) {
            val runner = effectRunner
            if (runner != null) {
                runner.runAll(requested)
            } else {
                pendingEffects.addAll(requested)
            }
        }
    }

    // Both Channel admission and MutableStateFlow writes are thread-safe.
    private fun enqueue(command: Command): Boolean {
        val cookie = ActionTrace.begin()
        val accepted = commands.trySend(Queued(command, cookie)).isSuccess
        if (!accepted) {
            ActionTrace.end(cookie)
            mutableError.value =
                "Python action queue unavailable"
        }
        return accepted
    }

    // Boundary failures become diagnostics, never UI crashes.
    @Suppress("TooGenericExceptionCaught")
    private fun perform(
        cookies: List<Int>,
        queuedAt: Long,
        operation: () -> Boolean,
    ) {
        var shown = false
        try {
            val started = System.nanoTime()
            // A batch none of which reached Python has nothing new to pull.
            if (!ActionTrace.stage("pycompose.python", operation)) return
            val ran = System.nanoTime()
            // Python draws the snapshot once, when it is pulled, for every command.
            val envelope =
                ActionTrace.stage("pycompose.pull") {
                    bridge.fetchLatest(stream.surface, stream.serial)
                }
            val pulled = System.nanoTime()
            // Fetched between stages, so the log's own call is counted in none of them.
            val phases = if (timePasses) bridge.fetchLastPass() else ""
            val resumed = System.nanoTime()
            val result = ActionTrace.stage("pycompose.apply") { stream.accept(envelope) }
            val applied = System.nanoTime()
            val timing =
                if (timePasses) {
                    PassTiming(
                        queue = PassTiming.millis(started - queuedAt),
                        python = PassTiming.millis(ran - started),
                        pull = PassTiming.millis(pulled - ran),
                        apply = PassTiming.millis(applied - resumed),
                        phases = phases,
                        commands = cookies.size,
                        appliedAt = applied,
                    )
                } else {
                    null
                }
            result
                .onSuccess { candidate ->
                    // Effects belong to the snapshot that carried them: a repeat
                    // pull of an unchanged snapshot must not replay them.
                    val previous = mutableSnapshot.value
                    val changed = candidate.snapshot != previous?.ir?.snapshot
                    if (changed || previous?.epoch != epoch) {
                        mutableSnapshot.value =
                            SessionSnapshot(candidate, epoch, cookies, stream.serial, timing)
                        shown = true
                    }
                    mutableError.value = bridge.fetchLatestError()
                    if (changed) {
                        runEffects(candidate)
                        saveAppData(candidate)
                    }
                }.onFailure { mutableError.value = it.message ?: "Invalid IR snapshot" }
        } catch (failure: Exception) {
            mutableError.value = failure.message ?: "Python worker failure"
        } finally {
            // A command that changed nothing on screen has no frame to close its span.
            if (!shown) cookies.forEach(ActionTrace::end)
        }
    }

    /**
     * Keep the app's own data so a rebuilt process can start where it left off.
     * Only what the app published in the snapshot is saved; the host invents none.
     *
     * App data lives in a Bundle, and a Bundle that is too large fails on save
     * with a TransactionTooLargeException that names nothing useful. Oversized
     * data is refused here with an explanation instead, and the app keeps running
     * on the state it already has rather than crashing on rotation.
     */
    private fun saveAppData(ir: ValidatedIr) {
        // Parsing already checked the shape and schema, so an app that published
        // nothing is the only case left to skip.
        val canonical = AppData.read(ir.snapshot.metadata, ir.snapshot.schemaVersion)
        if (canonical.isEmpty() || canonical == restore) {
            return
        }
        if (canonical.toByteArray(Charsets.UTF_8).size > SAVE_BUDGET_BYTES) {
            mutableError.value =
                "App state is ${canonical.length} characters, over the " +
                "${SAVE_BUDGET_BYTES / BYTES_PER_KB} KB this host can restore. " +
                "Keep only the current screen's state here and put the " +
                "rest in a repository."
            return
        }
        restore = canonical
        savedState[STATE] = canonical
    }

    fun close() {
        // A background result must never reach a closed view: the worker it would
        // re-render into no longer exists.
        resultSubscription.close()
        admissionSubscription.close()
        effectRunner = null
        pendingEffects.clear()
        commands.close()
        scope.cancel()
    }

    override fun onCleared() {
        close()
    }

    companion object {
        private const val QUEUE_CAPACITY = 64
        private const val STATE = "pycompose.data"
        private const val EPOCH = "pycompose.epoch"

        /**
         * Comfortably under Android's ~500 KB per-transaction Binder limit, so
         * several such bundles can share one save without tipping over it.
         */
        private const val SAVE_BUDGET_BYTES = 128 * 1024

        /** Divisor turning the byte budget into the kilobytes shown to the user. */
        private const val BYTES_PER_KB = 1024
    }
}
