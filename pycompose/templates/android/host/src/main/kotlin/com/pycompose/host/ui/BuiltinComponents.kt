package com.pycompose.host.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.takeOrElse
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.renderer.ComponentRegistry
import com.pycompose.renderer.PropResolver
import kotlinx.serialization.json.JsonPrimitive
import com.pycompose.ir.generated.Box as BoxNode
import com.pycompose.ir.generated.Checkbox as CheckboxNode
import com.pycompose.ir.generated.Column as ColumnNode
import com.pycompose.ir.generated.FilledButton as ButtonNode
import com.pycompose.ir.generated.FilterChip as FilterChipNode
import com.pycompose.ir.generated.Image as ImageNode
import com.pycompose.ir.generated.LazyColumn as ListNode
import com.pycompose.ir.generated.Row as RowNode
import com.pycompose.ir.generated.Scaffold as ScaffoldNode
import com.pycompose.ir.generated.Text as TextNode
import com.pycompose.ir.generated.TextButton as TextButtonNode
import com.pycompose.ir.generated.TextField as InputNode

/** Thin native adapters, not reimplementations of Material 3 component behavior. */
object BuiltinComponents {
    fun registry(resources: ResourceResolver? = null): ComponentRegistry =
        ComponentRegistry
            .Builder()
            .layouts()
            .displays(resources)
            .controls()
            .build()

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
            }.register("Spacer") { _, modifier, _ -> Spacer(modifier) }
            .register("Scaffold") { node, modifier, context ->
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

    private fun ComponentRegistry.Builder.controls(): ComponentRegistry.Builder =
        this
            .register("FilledButton") { node, modifier, context ->
                val button = node as ButtonNode
                Button(
                    onClick = { context.actions.dispatch(button.props.onClick) },
                    modifier = modifier,
                    enabled = button.props.enabled,
                ) {
                    Text(button.props.text)
                }
            }.register("TextField") { node, modifier, context ->
                val input = node as InputNode
                TextField(
                    value = input.props.value,
                    onValueChange = { value ->
                        context.event(input.props.onValueChange, JsonPrimitive(value))
                    },
                    modifier = modifier,
                    enabled = input.props.enabled,
                    label = input.props.label?.let { label -> { Text(label) } },
                )
            }.register("Checkbox") { node, modifier, context ->
                val checkbox = node as CheckboxNode
                Checkbox(
                    checked = checkbox.props.checked,
                    onCheckedChange = { value ->
                        context.event(checkbox.props.onCheckedChange, JsonPrimitive(value))
                    },
                    modifier = modifier,
                    enabled = checkbox.props.enabled,
                )
            }.register("TextButton") { node, modifier, context ->
                val button = node as TextButtonNode
                TextButton(
                    onClick = { context.actions.dispatch(button.props.onClick) },
                    modifier = modifier,
                    enabled = button.props.enabled,
                ) {
                    Text(button.props.text)
                }
            }.register("FilterChip") { node, modifier, context ->
                val chip = node as FilterChipNode
                FilterChip(
                    selected = chip.props.selected,
                    onClick = { context.actions.dispatch(chip.props.onClick) },
                    modifier = modifier,
                    enabled = chip.props.enabled,
                    label = { Text(chip.props.label) },
                )
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
