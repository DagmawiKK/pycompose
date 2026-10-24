package com.pycompose.host.ui

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SearchBarDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.renderer.ComponentRegistry
import com.pycompose.renderer.PropResolver
import com.pycompose.renderer.generated.ValueResolver
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import com.pycompose.ir.generated.Image as ImageNode
import com.pycompose.ir.generated.SearchBarInputField as SearchBarInputFieldNode
import com.pycompose.ir.generated.Text as TextNode
import com.pycompose.ir.generated.TextField as InputNode

/** Thin native adapters, not reimplementations of Material 3 component behavior. */
object BuiltinComponents {
    fun registry(resources: ResourceResolver? = null): ComponentRegistry =
        GeneratedAdapters
            .register(
                ComponentRegistry
                    .Builder()
                    .displays(resources)
                    .controls(),
            ).build()

    private fun ComponentRegistry.Builder.displays(
        resources: ResourceResolver?,
    ): ComponentRegistry.Builder =
        this
            .register("Text") { node, modifier, _ ->
                val text = node as TextNode
                ResourceText(
                    text.props,
                    modifier,
                    nativeColor(text.props.color),
                    textStyle(text.props.style),
                    resources,
                )
            }.register("Image") { node, modifier, _ ->
                val image = node as ImageNode
                ResourceImage(
                    image.props.resource,
                    image.props.contentDescription,
                    modifier,
                    resources,
                )
            }

    private fun ComponentRegistry.Builder.controls(): ComponentRegistry.Builder =
        textInputs()
            .searchFields()
            .statefulSearchFields()
            .sharedSearchBars()
            .tooltips()

    private fun ComponentRegistry.Builder.textInputs(): ComponentRegistry.Builder =
        register("TextField") { node, modifier, context ->
            val input = node as InputNode
            val caret = input.props.selection
            val onCaret = input.props.onSelectionChange
            val echoed = rememberEchoedText(input.id, input.props.value, caret?.toInt())
            val report: (String) -> Unit = { value ->
                echoed.typed(value)
                context.event(input.props.onValueChange, JsonPrimitive(value))
            }
            // Controlled when the app says where the caret is, which puts it in
            // the snapshot and makes it testable. Uncontrolled otherwise, where
            // Compose owns it and the app never sees it. Both halves must be
            // declared: one alone would either drop every caret report or reject
            // every keystroke.
            if (caret != null && onCaret != null) {
                TextField(
                    value = echoed.value,
                    // The caret travels back on the same callback that reports the
                    // text: the event channel carries one value per action, and M3
                    // has no selection callback of its own at this version. A caret
                    // moved without the text changing is therefore not reported.
                    onValueChange = { updated ->
                        val changed = updated.text != echoed.text
                        echoed.typed(updated)
                        if (changed) {
                            context.event(input.props.onValueChange, JsonPrimitive(updated.text))
                        }
                        context.event(onCaret, JsonPrimitive(updated.selection.start))
                    },
                    modifier = modifier,
                    enabled = input.props.enabled,
                    label = input.props.label?.let { text -> { Text(text) } },
                )
            } else {
                TextField(
                    value = echoed.text,
                    onValueChange = report,
                    modifier = modifier,
                    enabled = input.props.enabled,
                    label = input.props.label?.let { text -> { Text(text) } },
                )
            }
        }

    @OptIn(ExperimentalMaterial3Api::class)
    private fun ComponentRegistry.Builder.searchFields(): ComponentRegistry.Builder =
        register("SearchBarInputField") { node, modifier, context ->
            val field = node as SearchBarInputFieldNode
            // The native field owns the caret, but the app owns the text: the
            // latest keystroke stays until the app states other text.
            val query = rememberEchoedText(field.id, field.props.query)
            SearchBarDefaults.InputField(
                query = query.text,
                onQueryChange = { value ->
                    query.typed(value)
                    context.event(field.props.onQueryChange, JsonPrimitive(value))
                },
                onSearch = { query ->
                    context.event(field.props.onSearch, JsonPrimitive(query))
                },
                expanded = field.props.expanded,
                onExpandedChange = { expanded ->
                    context.event(field.props.onExpandedChange, JsonPrimitive(expanded))
                },
                modifier = modifier,
                enabled = field.props.enabled,
                placeholder = context.slot(field.children, "placeholder"),
                leadingIcon = context.slot(field.children, "leadingIcon"),
                trailingIcon = context.slot(field.children, "trailingIcon"),
            )
        }

    @Composable private fun textStyle(value: JsonElement): androidx.compose.ui.text.TextStyle {
        if (value is JsonObject) return ValueResolver.textStyle(value).getOrThrow()
        return legacyTextStyle((value as JsonPrimitive).content)
    }

    @Composable private fun legacyTextStyle(value: String) =
        with(MaterialTheme.typography) {
            PropResolver
                .enum(
                    value,
                    mapOf(
                        "bodyLarge" to bodyLarge,
                        "bodyMedium" to bodyMedium,
                        "bodySmall" to bodySmall,
                        "titleLarge" to titleLarge,
                        "titleMedium" to titleMedium,
                        "titleSmall" to titleSmall,
                        "headlineMedium" to headlineMedium,
                    ),
                ).getOrDefault(bodyMedium)
        }
}

/** Resolve theme-aware color data for the hand-written native adapters. */
@Composable
internal fun nativeColor(value: JsonElement?): Color =
    when (value) {
        is JsonObject -> ValueResolver.color(value).getOrDefault(Color.Unspecified)
        is JsonPrimitive -> PropResolver.color(value.content).getOrDefault(Color.Unspecified)
        else -> Color.Unspecified
    }
