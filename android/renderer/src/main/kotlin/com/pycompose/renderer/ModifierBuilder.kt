package com.pycompose.renderer

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.pycompose.ir.IrParser
import com.pycompose.renderer.generated.GeneratedModifiers
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive

/**
 * Fold ordered operations once. Any failed operation rejects the whole modifier.
 *
 * What each operation calls is generated from the catalog
 * ([GeneratedModifiers]); this only validates the program and folds it.
 */
class ModifierBuilder(
    private val actions: ActionDispatcher,
) {
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
                    val type = checkNotNull(operation["type"]?.jsonPrimitive).content
                    val applied =
                        GeneratedModifiers.apply(type, scope, operation) {
                            actions.dispatch(it)
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
}
