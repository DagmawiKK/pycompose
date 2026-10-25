package com.pycompose.renderer

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.semantics.testTag
import androidx.compose.ui.semantics.traversalIndex
import com.pycompose.ir.IrParser
import com.pycompose.renderer.generated.ScopedModifiers
import com.pycompose.renderer.generated.ValueResolver
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive

/** Fold ordered operations once. Any failed operation rejects the whole modifier. */
class ModifierBuilder(
    private val actions: ActionDispatcher,
) {
    private val operations: Map<String, @Composable (JsonObject) -> Modifier> =
        mapOf(
            "padding" to {
                val value = it["value"]
                if (value is JsonObject) {
                    Modifier.padding(ValueResolver.paddingValues(value).getOrThrow())
                } else {
                    Modifier.padding(PropResolver.dp(it.number("value")).getOrThrow())
                }
            },
            "fillMaxWidth" to {
                val fraction = it.number("fraction")
                require(fraction.isFinite() && fraction in 0.0..1.0)
                Modifier.fillMaxWidth(fraction.toFloat())
            },
            "size" to {
                val width = it.dimension("width")
                val height = it.dimension("height")
                Modifier.size(width, height)
            },
            "clip" to {
                val value = it["shape"]
                val shape =
                    if (value is JsonObject) {
                        ValueResolver
                            .shape(
                                value,
                            ).getOrThrow()
                    } else {
                        PropResolver.shape(it.string("shape")).getOrThrow()
                    }
                Modifier.clip(shape)
            },
            "clickable" to {
                val actionId = it.string("onClick")
                val enabled = checkNotNull(it["enabled"]?.jsonPrimitive?.booleanOrNull)
                Modifier.clickable(enabled = enabled) { actions.dispatch(actionId) }
            },
            "semantics" to { semantics(it) },
            "background" to
                { Modifier.background(ValueResolver.brush(it.getValue("brush")).getOrThrow()) },
            "windowInsetsPadding" to
                {
                    Modifier.windowInsetsPadding(
                        ValueResolver.windowInsets(it.getValue("insets")).getOrThrow(),
                    )
                },
        )

    /**
     * The modifier [program] describes, or why it cannot apply.
     *
     * @param program The node's wire modifier, or null for none.
     * @param scope The receiver the node's parent lambda carries, which the
     *   operations a scope declares (`weight`, `menuAnchor`) apply on.
     */
    @Composable
    fun build(
        program: JsonObject?,
        scope: Any? = null,
    ): Result<Modifier> {
        if (program == null) return Result.success(Modifier)
        val prepared =
            runCatching {
                val sequence =
                    program["operations"] as? JsonArray
                        ?: error("Expected modifier operations")
                val ids =
                    sequence
                        .mapNotNull {
                            (it as? JsonObject)?.get("onClick") as? JsonPrimitive
                        }.map { it.content }
                        .toSet()
                IrParser.validateModifier(program, ids).getOrThrow()
                sequence.map { it as JsonObject }
            }
        return prepared.fold(
            onSuccess = { sequence ->
                sequence.fold(Result.success<Modifier>(Modifier)) { built, operation ->
                    val modifier = built.getOrNull() ?: return@fold built
                    val type = operation.string("type")
                    val hand = operations[type]
                    val applied =
                        if (hand !=
                            null
                        ) {
                            hand(operation)
                        } else {
                            ScopedModifiers.apply(type, scope, operation)
                        }
                    if (applied == null) {
                        Result.failure(IllegalStateException("$type needs a parent declaring it"))
                    } else {
                        Result.success(modifier.then(applied))
                    }
                }
            },
            onFailure = { Result.failure(it) },
        )
    }

    /** Accessibility semantics the native component does not carry itself (plan 31 §16.6). */
    private fun semantics(operation: JsonObject): Modifier {
        val description = operation.optional("contentDescription")
        val state = operation.optional("stateDescription")
        val role = operation.optional("role")?.let { checkNotNull(ROLES[it]) }
        val live = operation.optional("liveRegion")?.let { checkNotNull(LIVE_REGIONS[it]) }
        val tag = operation.optional("testTag")
        val heading = operation["heading"]?.jsonPrimitive?.booleanOrNull == true
        val index = operation["traversalIndex"]?.jsonPrimitive?.doubleOrNull
        return Modifier.semantics {
            description?.let { contentDescription = it }
            state?.let { stateDescription = it }
            role?.let { this.role = it }
            live?.let { liveRegion = it }
            tag?.let { testTag = it }
            if (heading) heading()
            index?.let { traversalIndex = it.toFloat() }
        }
    }

    private fun JsonObject.optional(key: String): String? = if (key in this) string(key) else null

    private fun JsonObject.number(key: String): Double =
        checkNotNull(this[key]?.jsonPrimitive?.doubleOrNull)

    @Composable
    private fun JsonObject.dimension(key: String): androidx.compose.ui.unit.Dp {
        val value = getValue(key)
        val dimension =
            if (value is JsonObject) {
                ValueResolver
                    .dp(
                        value,
                    ).getOrThrow()
            } else {
                PropResolver.dp(number(key)).getOrThrow()
            }
        require(dimension.value >= 0f)
        return dimension
    }

    private fun JsonObject.string(key: String): String {
        val value = checkNotNull(this[key] as? JsonPrimitive)
        require(value.isString)
        return value.content
    }
}

private val ROLES =
    mapOf(
        "button" to Role.Button,
        "checkbox" to Role.Checkbox,
        "switch" to Role.Switch,
        "radioButton" to Role.RadioButton,
        "tab" to Role.Tab,
        "image" to Role.Image,
        "dropdownList" to Role.DropdownList,
        "valuePicker" to Role.ValuePicker,
        "carousel" to Role.Carousel,
    )

private val LIVE_REGIONS =
    mapOf(
        "polite" to LiveRegionMode.Polite,
        "assertive" to LiveRegionMode.Assertive,
    )
