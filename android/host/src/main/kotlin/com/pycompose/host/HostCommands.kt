package com.pycompose.host

import com.pycompose.renderer.Action
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** A command and the trace span opened when it was queued. */
internal data class Queued(
    val command: Command,
    val cookie: Int,
    val queuedAt: Long = System.nanoTime(),
)

internal sealed interface Command {
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

    /** The window of a lazy list the host now shows; a newer one supersedes it. */
    data class Window(
        val key: String,
        val first: Int,
        val last: Int,
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

/**
 * Drop each queued command a newer one of the same kind supersedes.
 *
 * A settled report carries the holder's whole value, so the newest to an action says
 * everything an older one would have, and the app's echo of its number answers both. A
 * window request names everything the list wants, so the newest per list stands alone.
 */
internal fun coalesce(batch: List<Queued>): List<Queued> {
    val kinds = batch.map { supersedes(it.command) }
    val latest = kinds.withIndex().mapNotNull { (index, kind) -> kind?.let { it to index } }.toMap()
    return batch.filterIndexed { index, queued ->
        val superseded = kinds[index]?.let { latest[it] != index } ?: false
        if (superseded) ActionTrace.end(queued.cookie)
        !superseded
    }
}

/** What a newer command must share with [command] to supersede it, or null for none. */
private fun supersedes(command: Command): String? =
    when (command) {
        is Command.Dispatch ->
            command.action
                .takeIf {
                    it.seq != null
                }?.let { "report:${it.actionId}" }
        is Command.Window -> "window:${command.key}"
        else -> null
    }
