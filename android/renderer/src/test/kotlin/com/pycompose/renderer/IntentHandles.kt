package com.pycompose.renderer

import com.pycompose.ir.Intents
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject

/** The handle the host gives the intent `{"fields": fields, "intent": handler}`. */
internal fun intent(
    handler: String,
    fields: String = "{}",
): String =
    Intents.handle(Json.parseToJsonElement("""{"fields":$fields,"intent":"$handler"}""").jsonObject)
