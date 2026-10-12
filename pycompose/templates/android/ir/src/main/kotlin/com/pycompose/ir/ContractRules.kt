package com.pycompose.ir

/** Generated registry property constraints, independent of platform types. */
data class PropertyRule(
    val type: String,
    val required: Boolean = false,
    val values: Set<String> = emptySet(),
    val minimum: Double? = null,
    val maximum: Double? = null,
)

/** Registered component structure and property constraints. */
data class ComponentRule(
    val childrenAllowed: Boolean,
    val minimumChildren: Int = 0,
    val props: Map<String, PropertyRule>,
)
