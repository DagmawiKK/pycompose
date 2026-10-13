package com.pycompose.host

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import com.pycompose.host.bridge.BridgeSurface
import com.pycompose.ir.IrParser
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

/** Host owns only latest IR and minimal navigation state, never the Python Store. */
class PyComposeViewModel(
    private val bridge: BridgeSurface,
    private val savedState: SavedStateHandle,
    dispatcher: CoroutineDispatcher,
) : ViewModel() {
    private val scope = CoroutineScope(SupervisorJob() + dispatcher)
    private val commands = Channel<Command>(QUEUE_CAPACITY)
    private val parser = IrParser()
    private val mutableSnapshot = MutableStateFlow<ValidatedIr?>(null)
    private val mutableError = MutableStateFlow("")
    val snapshot: StateFlow<ValidatedIr?> = mutableSnapshot.asStateFlow()
    val error: StateFlow<String> = mutableError.asStateFlow()
    private var route = savedState.get<String>("route") ?: "home"

    init {
        val restored = route
        scope.launch {
            perform { bridge.start(restored) }
            for (command in commands) {
                perform {
                    when (command) {
                        is Command.Dispatch -> bridge.acceptAction(command.action.toJson())
                        is Command.Reload -> bridge.reload(command.route)
                        is Command.Navigate -> bridge.start(command.route)
                    }
                }
            }
        }
    }

    fun dispatch(action: Action) {
        enqueue(Command.Dispatch(action))
    }

    fun reload() {
        enqueue(Command.Reload(route))
    }

    /** Called from the UI thread. Only this minimal route is saved across process death. */
    fun navigate(destination: String) {
        require(destination.isNotBlank())
        route = destination
        savedState["route"] = destination
        enqueue(Command.Navigate(destination))
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
                    if (candidate.snapshot != mutableSnapshot.value?.snapshot) {
                        mutableSnapshot.value = candidate
                    }
                    mutableError.value = bridge.fetchLatestError()
                }.onFailure { mutableError.value = it.message ?: "Invalid IR snapshot" }
        } catch (failure: Exception) {
            mutableError.value = failure.message ?: "Python worker failure"
        }
    }

    fun close() {
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

        data class Reload(
            val route: String,
        ) : Command

        data class Navigate(
            val route: String,
        ) : Command
    }

    companion object {
        private const val QUEUE_CAPACITY = 64
    }
}
