package com.pycompose.host.ui

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SearchBarDefaults
import com.pycompose.host.resources.ResourceResolver
import com.pycompose.renderer.ComponentRegistry
import com.pycompose.renderer.edit
import com.pycompose.renderer.edited
import kotlinx.serialization.json.JsonPrimitive
import com.pycompose.ir.generated.SearchBarInputField as SearchBarInputFieldNode

/** Thin native adapters, not reimplementations of Material 3 component behavior. */
object BuiltinComponents {
    fun registry(resources: ResourceResolver? = null): ComponentRegistry =
        GeneratedAdapters
            .register(ComponentRegistry.Builder().controls(), resources)
            .build()

    private fun ComponentRegistry.Builder.controls(): ComponentRegistry.Builder =
        searchFields()
            .statefulSearchFields()
            .sharedSearchBars()

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
}
