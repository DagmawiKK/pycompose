package com.pycompose.host

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import com.pycompose.host.bridge.BridgeSurface
import com.pycompose.ir.AppBindings
import com.pycompose.ir.AppData
import com.pycompose.ir.EffectRequest
import com.pycompose.ir.Effects
import com.pycompose.ir.IrParser
import com.pycompose.ir.Lifecycle
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
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * An accepted snapshot paired atomically with its native session lifetime.
 *
 * @param ir Validated wire data to render.
 * @param epoch Host-local generation, retained on rotation and advanced on Python restart.
 */
data class SessionSnapshot(
    val ir: ValidatedIr,
    val epoch: Long,
)

/** Host owns only latest IR and minimal navigation state, never the Python Store. */
class PyComposeViewModel(
    private val bridge: BridgeSurface,
    private val savedState: SavedStateHandle,
    dispatcher: CoroutineDispatcher,
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
    private val commands = Channel<Command>(QUEUE_CAPACITY)
    private val parser = IrParser()
    private val mutableSnapshot = MutableStateFlow<SessionSnapshot?>(null)
    private val mutableError = MutableStateFlow("")
    val snapshot: StateFlow<SessionSnapshot?> = mutableSnapshot.asStateFlow()
    val error: StateFlow<String> = mutableError.asStateFlow()
    private var route = savedState.get<String>("route") ?: "home"
    private var restore = savedState.get<String>(STATE) ?: ""
    private var epoch = (savedState.get<Long>(EPOCH) ?: -1L) + 1L

    init {
        savedState[EPOCH] = epoch
        // Background Python results arrive from any thread and are queued here, so
        // the worker still only ever sees them as ordinary actions.
        AsyncResult.listen { actionId, payload ->
            runCatching {
                val element = Json.parseToJsonElement(payload)
                require(element is JsonObject) { "Async result must be an object" }
                Action(actionId, element)
            }.onSuccess { action ->
                enqueue(Command.Push(action))
            }.onFailure { error ->
                mutableError.value = "Async result failed: ${error.message}"
            }
        }
        val restored = route
        val saved = restore
        scope.launch {
            perform { bridge.start(restored, saved) }
            for (command in commands) {
                perform {
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
                        is Command.Push -> {
                            // A background result, delivered exactly as a tap would
                            // be: the payload is the app's, and its handler's
                            // declared contract is what checks it.
                            bridge.acceptAction(command.action.toJson())
                        }
                    }
                }
            }
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
        enqueue(Command.Dispatch(action))
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

    private fun enqueue(command: Command) {
        if (commands.trySend(command).isFailure) {
            mutableError.value =
                "Python action queue unavailable"
        }
    }

    // Boundary failures become diagnostics, never UI crashes.
    @Suppress("TooGenericExceptionCaught")
    private fun perform(operation: () -> Unit) {
        try {
            operation()
            val source = bridge.fetchLatestSnapshot()
            val result = parser.parse(source)
            result
                .onSuccess { candidate ->
                    // Effects belong to the snapshot that carried them: a repeat
                    // pull of an unchanged snapshot must not replay them.
                    val previous = mutableSnapshot.value
                    val changed = candidate.snapshot != previous?.ir?.snapshot
                    if (changed || previous?.epoch != epoch) {
                        mutableSnapshot.value = SessionSnapshot(candidate, epoch)
                    }
                    mutableError.value = bridge.fetchLatestError()
                    if (changed) {
                        runEffects(candidate)
                        saveAppData(candidate)
                    }
                }.onFailure { mutableError.value = it.message ?: "Invalid IR snapshot" }
        } catch (failure: Exception) {
            mutableError.value = failure.message ?: "Python worker failure"
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
        AsyncResult.listen(null)
        effectRunner = null
        pendingEffects.clear()
        commands.close()
        scope.cancel()
    }

    override fun onCleared() {
        close()
    }

    private sealed interface Command {
        data class Dispatch(
            val action: Action,
        ) : Command

        data class Lifecycle(
            val event: String,
            val payload: JsonObject,
        ) : Command {
            val action: Action = Action(event, payload)
        }

        data class Reload(
            val route: String,
        ) : Command

        /** A background result, queued from whatever thread produced it. */
        data class Push(
            val action: Action,
        ) : Command

        data class Navigate(
            val route: String,
        ) : Command {
            /** The route change, delivered to Python as an ordinary action. */
            val action: Action =
                Action(
                    "onRouteChanged",
                    JsonObject(mapOf("route" to JsonPrimitive(route))),
                )
        }
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
