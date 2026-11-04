package com.pycompose.host.ui

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SearchBarDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.renderer.ComponentRegistry
import com.pycompose.renderer.edit
import com.pycompose.renderer.edited
import com.pycompose.renderer.generated.ValueResolver
import kotlinx.serialization.json.JsonElement
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
            .register("Text") { node, modifier, context ->
                val text = node as TextNode
                ResourceText(
                    text.props,
                    modifier,
                    context.nativeColor(text.props.color),
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
                    image.props.contentScale?.let {
                        ValueResolver.contentScale(it).getOrThrow()
                    } ?: ContentScale.Fit,
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
            // Controlled when the app says where the caret is, which puts it in
            // the snapshot and makes it testable. Uncontrolled otherwise, where
            // Compose owns it and the app never sees it. Both halves must be
            // declared: one alone would either drop every caret report or reject
            // every keystroke.
            if (caret != null && onCaret != null) {
                val value = input.props.value
                val stated =
                    TextFieldValue(value, TextRange(caret.toInt().coerceIn(0, value.length)))
                val field = context.edited(input.id, stated, input.props.onValueChange, onCaret)
                TextField(
                    value = field.value,
                    // The caret travels back on the same callback that reports the
                    // text: M3 has no selection callback of its own at this version.
                    onValueChange = { updated: TextFieldValue ->
                        val text = input.props.onValueChange to JsonPrimitive(updated.text)
                        val at = onCaret to JsonPrimitive(updated.selection.start)
                        val changed = updated.text != field.value.text
                        context.edit(field, updated, if (changed) mapOf(text, at) else mapOf(at))
                    },
                    modifier = modifier,
                    enabled = input.props.enabled,
                    label = input.props.label?.let { text -> { Text(text) } },
                )
            } else {
                val field = context.edited(input.id, input.props.value, input.props.onValueChange)
                TextField(
                    value = field.value,
                    onValueChange = {
                        context.edit(field, it, input.props.onValueChange, JsonPrimitive(it))
                    },
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
            // The native field owns the caret, but the app owns the text.
            val query = context.edited(field.id, field.props.query, field.props.onQueryChange)
            SearchBarDefaults.InputField(
                query = query.value,
                onQueryChange = {
                    context.edit(
                        query,
                        it,
                        field.props.onQueryChange,
                        JsonPrimitive(it),
                    )
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

    @Composable private fun textStyle(value: JsonElement?): androidx.compose.ui.text.TextStyle =
        value?.let { ValueResolver.textStyle(it).getOrThrow() }
            ?: MaterialTheme.typography.bodyMedium
}
