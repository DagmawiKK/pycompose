package com.pycompose.host

import com.pycompose.renderer.Action
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** A command and the trace span opened when it was queued. */
internal data class Queued(
    val command: Command,
    val cookie: Int,
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
 * Drop each settled report a newer report to the same action supersedes.
 *
 * A report carries the holder's whole settled value, so the newest says everything an
 * older one still queued would have, and the app's echo of its number answers both.
 */
internal fun coalesce(batch: List<Queued>): List<Queued> {
    val reports =
        batch.map {
            (it.command as? Command.Dispatch)?.action?.takeIf { action ->
                action.seq !=
                    null
            }
        }
    val latest =
        reports
            .withIndex()
            .mapNotNull { (index, action) ->
                action?.let {
                    it.actionId to
                        index
                }
            }.toMap()
    return batch.filterIndexed { index, queued ->
        val superseded = reports[index]?.let { latest[it.actionId] != index } ?: false
        if (superseded) ActionTrace.end(queued.cookie)
        !superseded
    }
}
