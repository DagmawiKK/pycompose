@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.pycompose.host.ui

import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.SearchBarDefaults
import com.pycompose.renderer.ComponentRegistry
import com.pycompose.renderer.generated.ValueResolver
import com.pycompose.renderer.textInputState
import kotlinx.serialization.json.JsonPrimitive
import com.pycompose.ir.generated.StatefulSearchBarInputField as StatefulInputNode

/** The state-based overload keeps native input behavior and presentation defaults. */
internal fun ComponentRegistry.Builder.statefulSearchFields(): ComponentRegistry.Builder =
    register("StatefulSearchBarInputField") { node, modifier, context ->
        val field = node as StatefulInputNode
        SearchBarDefaults.InputField(
            state =
                context.textInputState(
                    field.props.text,
                    field.props.onEdit,
                    field.props.selectionStart,
                    field.props.selectionEnd,
                    field.props.revision,
                ),
            onSearch = { context.event(field.props.onSearch, JsonPrimitive(it)) },
            expanded = field.props.expanded,
            onExpandedChange = { context.event(field.props.onExpandedChange, JsonPrimitive(it)) },
            modifier = modifier,
            enabled = field.props.enabled,
            readOnly = field.props.readOnly,
            textStyle =
                field.props.textStyle?.let { ValueResolver.textStyle(it).getOrThrow() }
                    ?: LocalTextStyle.current,
            placeholder = context.slot(field.children, "placeholder"),
            leadingIcon = context.slot(field.children, "leadingIcon"),
            trailingIcon = context.slot(field.children, "trailingIcon"),
            prefix = context.slot(field.children, "prefix"),
            suffix = context.slot(field.children, "suffix"),
            shape =
                field.props.shape?.let { ValueResolver.shape(it).getOrThrow() }
                    ?: SearchBarDefaults.inputFieldShape,
            colors =
                field.props.colors?.let { ValueResolver.textFieldColors(it).getOrThrow() }
                    ?: SearchBarDefaults.inputFieldColors(),
        )
    }
