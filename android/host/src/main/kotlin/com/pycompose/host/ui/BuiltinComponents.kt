package com.pycompose.host.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.takeOrElse
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.renderer.ComponentRegistry
import com.pycompose.renderer.PropResolver
import kotlinx.serialization.json.JsonPrimitive
import com.pycompose.ir.generated.Box as BoxNode
import com.pycompose.ir.generated.Column as ColumnNode
import com.pycompose.ir.generated.Image as ImageNode
import com.pycompose.ir.generated.LazyColumn as ListNode
import com.pycompose.ir.generated.Row as RowNode
import com.pycompose.ir.generated.Scaffold as ScaffoldNode
import com.pycompose.ir.generated.Text as TextNode
import com.pycompose.ir.generated.TextField as InputNode

/** Thin native adapters, not reimplementations of Material 3 component behavior. */
object BuiltinComponents {
    fun registry(resources: ResourceResolver? = null): ComponentRegistry =
        GeneratedAdapters
            .register(
                ComponentRegistry
                    .Builder()
                    .layouts()
                    .displays(resources)
                    .controls(),
            ).build()

    private fun ComponentRegistry.Builder.layouts(): ComponentRegistry.Builder =
        this
            .register("Column") { node, modifier, context ->
                val column = node as ColumnNode
                val alignment =
                    PropResolver
                        .horizontal(column.props.horizontalAlignment)
                        .getOrDefault(Alignment.Start)
                Column(modifier, horizontalAlignment = alignment) {
                    context.children(column.children)
                }
            }.register("Row") { node, modifier, context ->
                val row = node as RowNode
                val alignment =
                    PropResolver
                        .vertical(row.props.verticalAlignment)
                        .getOrDefault(Alignment.Top)
                Row(modifier, verticalAlignment = alignment) {
                    context.children(row.children)
                }
            }.register("Box") { node, modifier, context ->
                val box = node as BoxNode
                val alignment =
                    PropResolver
                        .alignment(box.props.contentAlignment)
                        .getOrDefault(Alignment.TopStart)
                Box(modifier, contentAlignment = alignment) {
                    context.children(box.children)
                }
            }.register("LazyColumn") { node, modifier, context ->
                val list = node as ListNode
                val arrangement =
                    PropResolver
                        .arrangement(list.props.verticalArrangement)
                        .getOrDefault(Arrangement.Top)
                LazyColumn(modifier, verticalArrangement = arrangement) {
                    items(list.children, key = { it.id }) { context.node(it) }
                }
            }.register("Scaffold") { node, modifier, context ->
                val scaffold = node as ScaffoldNode
                val container =
                    color(scaffold.props.containerColor)
                        .takeOrElse { MaterialTheme.colorScheme.background }
                Scaffold(modifier, containerColor = container) { padding ->
                    Column(Modifier.padding(padding)) { context.children(scaffold.children) }
                }
            }

    private fun ComponentRegistry.Builder.displays(
        resources: ResourceResolver?,
    ): ComponentRegistry.Builder =
        this
            .register("Text") { node, modifier, _ ->
                val text = node as TextNode
                ResourceText(
                    text.props,
                    modifier,
                    color(text.props.color),
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

    private fun ComponentRegistry.Builder.controls(): ComponentRegistry.Builder = textInputs()

    private fun ComponentRegistry.Builder.textInputs(): ComponentRegistry.Builder =
        register("TextField") { node, modifier, context ->
            val input = node as InputNode
            val report: (String) -> Unit = { value ->
                context.event(input.props.onValueChange, JsonPrimitive(value))
            }
            val caret = input.props.selection
            val onCaret = input.props.onSelectionChange
            // Controlled when the app says where the caret is, which puts it in
            // the snapshot and makes it testable. Uncontrolled otherwise, where
            // Compose owns it and the app never sees it. Both halves must be
            // declared: one alone would either drop every caret report or reject
            // every keystroke.
            if (caret != null && onCaret != null) {
                val wanted = input.props.value
                val offset = caret.toInt().coerceIn(0, wanted.length)
                TextField(
                    value = TextFieldValue(text = wanted, selection = TextRange(offset)),
                    // The caret travels back on the same callback that reports the
                    // text: the event channel carries one value per action, and M3
                    // has no selection callback of its own at this version. A caret
                    // moved without the text changing is therefore not reported.
                    onValueChange = { updated ->
                        report(updated.text)
                        context.event(onCaret, JsonPrimitive(updated.selection.start))
                    },
                    modifier = modifier,
                    enabled = input.props.enabled,
                    label = input.props.label?.let { text -> { Text(text) } },
                )
            } else {
                TextField(
                    value = input.props.value,
                    onValueChange = report,
                    modifier = modifier,
                    enabled = input.props.enabled,
                    label = input.props.label?.let { text -> { Text(text) } },
                )
            }
        }

    private fun color(value: String?): Color =
        value?.let { PropResolver.color(it).getOrDefault(Color.Unspecified) } ?: Color.Unspecified

    @Composable private fun textStyle(value: String) =
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
