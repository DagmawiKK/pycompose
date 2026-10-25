package com.pycompose.ir

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.longOrNull

/**
 * The latest report sequence number the app answered, per action.
 *
 * Every settled value a host holder reports carries the next number for its action,
 * and the snapshot echoes the latest one the app processed. A holder drives towards
 * the app's desired value only once every report it sent is answered: until then the
 * desired value answers an older report, and driving to it would undo a newer gesture.
 */
object Echoes {
    /** The echoed numbers by action id; empty when the snapshot echoes none. */
    fun read(metadata: JsonObject?): Map<String, Long> {
        val raw = metadata?.get("echoes") ?: return emptyMap()
        require(raw is JsonObject) { "echoes must be an object" }
        return raw.mapValues { (_, seq) ->
            (seq as? JsonPrimitive)
                ?.takeUnless { it.isString }
                ?.longOrNull
                ?.takeIf { it > 0 }
                ?: error("echoes must hold positive integers")
        }
    }
}
