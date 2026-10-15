package com.pycompose.ir

import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonEncoder
import kotlinx.serialization.json.JsonNull

/** A prop can be omitted, explicitly null, or supplied without losing wire presence. */
@Serializable(with = OptionalValueSerializer::class)
sealed interface OptionalValue {
    data object Absent : OptionalValue

    data object Null : OptionalValue

    data class Present(
        val value: JsonElement,
    ) : OptionalValue
}

/** Absence is a model default, never a serialized sentinel. */
object OptionalValueSerializer : KSerializer<OptionalValue> {
    override val descriptor: SerialDescriptor = JsonElement.serializer().descriptor

    override fun deserialize(decoder: Decoder): OptionalValue =
        when (val value = (decoder as JsonDecoder).decodeJsonElement()) {
            JsonNull -> OptionalValue.Null
            else -> OptionalValue.Present(value)
        }

    override fun serialize(
        encoder: Encoder,
        value: OptionalValue,
    ) {
        val data =
            when (value) {
                OptionalValue.Absent -> error("Absent props must not be serialized")
                OptionalValue.Null -> JsonNull
                is OptionalValue.Present -> value.value
            }
        (encoder as JsonEncoder).encodeJsonElement(data)
    }
}
