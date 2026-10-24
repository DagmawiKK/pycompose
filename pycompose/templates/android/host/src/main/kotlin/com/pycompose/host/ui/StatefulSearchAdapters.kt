@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.pycompose.host.ui

import androidx.compose.material3.ExpandedDockedSearchBar
import androidx.compose.material3.ExpandedFullScreenSearchBar
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.SearchBar
import androidx.compose.material3.SearchBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.unit.dp
import com.pycompose.ir.generated.UiNode
import com.pycompose.renderer.ComponentRegistry
import com.pycompose.renderer.LocalHostSearchState
import com.pycompose.renderer.RenderContext
import com.pycompose.renderer.generated.ValueResolver
import com.pycompose.renderer.searchState
import com.pycompose.renderer.textInputState
import kotlinx.serialization.json.JsonPrimitive
import com.pycompose.ir.generated.ExpandedDockedSearchBar as DockedNode
import com.pycompose.ir.generated.ExpandedFullScreenSearchBar as FullScreenNode
import com.pycompose.ir.generated.SearchBarStateInputField as SearchInputNode
import com.pycompose.ir.generated.StatefulSearchBar as StatefulSearchBarNode
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

/**
 * One owner for editing, selection, revision and expansion, shared by every surface.
 *
 * The collapsed bar and the expanded results surface are two views of one
 * search. Composing them from one node lets the host create the native
 * `TextFieldState` and `SearchBarState` once and hand the same pair to the
 * input and expanded slots, so neither a snapshot pull nor an expansion can
 * fork the text or lose the selection.
 */
internal fun ComponentRegistry.Builder.sharedSearchBars(): ComponentRegistry.Builder =
    register("StatefulSearchBar") { node, modifier, context ->
        val search = node as StatefulSearchBarNode
        val state =
            context.searchState(
                expanded = search.props.expanded,
                onExpandedChange = search.props.onExpandedChange,
                text = search.props.text,
                selectionStart = search.props.selectionStart,
                selectionEnd = search.props.selectionEnd,
                revision = search.props.revision,
                onEdit = search.props.onEdit,
            )
        CompositionLocalProvider(LocalHostSearchState provides state) {
            SearchBar(
                state = state.bar,
                inputField = context.searchInputField(search.children, search.id),
                modifier = modifier,
                shape =
                    search.props.shape?.let { ValueResolver.shape(it).getOrThrow() }
                        ?: SearchBarDefaults.inputFieldShape,
                tonalElevation =
                    search.props.tonalElevation?.dp ?: SearchBarDefaults.TonalElevation,
                shadowElevation =
                    search.props.shadowElevation?.dp ?: SearchBarDefaults.ShadowElevation,
            )
            context.slot(search.children, "expandedBar")?.invoke()
        }
    }.stateInputFields().dockedExpandedBars().fullScreenExpandedBars()

/**
 * A field that reads the owner's native pair instead of declaring a second one.
 *
 * The state-based `InputField` overload couples focus to expansion through the
 * shared `SearchBarState`, so typing and dismissal behave exactly as the
 * collapsed field does.
 */
private fun ComponentRegistry.Builder.stateInputFields(): ComponentRegistry.Builder =
    register("SearchBarStateInputField") { node, modifier, context ->
        val field = node as SearchInputNode
        val owner = LocalHostSearchState.current
        if (owner == null) {
            LaunchedEffect(node.id) {
                context.diagnostic(
                    "Cannot render ${node.id}: SearchBarStateInputField needs " +
                        "a StatefulSearchBar owner",
                )
            }
        } else {
            SearchBarDefaults.InputField(
                textFieldState = owner.text,
                searchBarState = owner.bar,
                onSearch = { context.event(field.props.onSearch, JsonPrimitive(it)) },
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
    }

/** The docked results surface, shown in a popup over the collapsed bar. */
private fun ComponentRegistry.Builder.dockedExpandedBars(): ComponentRegistry.Builder =
    register("ExpandedDockedSearchBar") { node, modifier, context ->
        val docked = node as DockedNode
        val owner = LocalHostSearchState.current
        if (owner == null) {
            LaunchedEffect(node.id) {
                context.diagnostic(
                    "Cannot render ${node.id}: ExpandedDockedSearchBar needs " +
                        "a StatefulSearchBar owner",
                )
            }
        } else {
            ExpandedDockedSearchBar(
                state = owner.bar,
                inputField = context.searchInputField(docked.children, docked.id),
                modifier = modifier,
                shape =
                    docked.props.shape?.let { ValueResolver.shape(it).getOrThrow() }
                        ?: SearchBarDefaults.dockedShape,
                tonalElevation =
                    docked.props.tonalElevation?.dp ?: SearchBarDefaults.TonalElevation,
                shadowElevation =
                    docked.props.shadowElevation?.dp ?: SearchBarDefaults.ShadowElevation,
                content = { context.childrenIn(this, docked.children) },
            )
        }
    }

/** The full-screen results surface; its dialog is the component's own window. */
private fun ComponentRegistry.Builder.fullScreenExpandedBars(): ComponentRegistry.Builder =
    register("ExpandedFullScreenSearchBar") { node, modifier, context ->
        val full = node as FullScreenNode
        val owner = LocalHostSearchState.current
        if (owner == null) {
            LaunchedEffect(node.id) {
                context.diagnostic(
                    "Cannot render ${node.id}: ExpandedFullScreenSearchBar needs " +
                        "a StatefulSearchBar owner",
                )
            }
        } else {
            ExpandedFullScreenSearchBar(
                state = owner.bar,
                inputField = context.searchInputField(full.children, full.id),
                modifier = modifier,
                collapsedShape =
                    full.props.collapsedShape?.let { ValueResolver.shape(it).getOrThrow() }
                        ?: SearchBarDefaults.inputFieldShape,
                tonalElevation =
                    full.props.tonalElevation?.dp ?: SearchBarDefaults.TonalElevation,
                shadowElevation =
                    full.props.shadowElevation?.dp ?: SearchBarDefaults.ShadowElevation,
                windowInsets = { SearchBarDefaults.fullScreenWindowInsets },
                content = { context.childrenIn(this, full.children) },
            )
        }
    }

/**
 * The node's input-field slot, or an empty lambda with one diagnostic when absent.
 *
 * Both native surfaces require a field; an empty one degrades to a results-only
 * surface instead of crashing the host, and the diagnostic names the missing
 * declaration once per node.
 */
@Composable
private fun RenderContext.searchInputField(
    nodes: List<UiNode>,
    id: String,
): @Composable () -> Unit {
    val filled = slot(nodes, "inputField")
    if (filled != null) return filled
    LaunchedEffect(id) {
        diagnostic("Cannot render $id: search surface needs an inputField slot")
    }
    return {}
}
