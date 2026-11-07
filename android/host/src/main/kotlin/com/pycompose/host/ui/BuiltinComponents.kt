package com.pycompose.host.ui

import com.pycompose.host.resources.ResourceResolver
import com.pycompose.renderer.ComponentRegistry

/** Thin native adapters, not reimplementations of Material 3 component behavior. */
object BuiltinComponents {
    fun registry(resources: ResourceResolver? = null): ComponentRegistry =
        GeneratedAdapters.register(ComponentRegistry.Builder(), resources).build()
}
