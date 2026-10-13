package com.pycompose.ir

/** Name-only reference: no Android resource IDs and no filesystem traversal. */
class ResourceReference private constructor(
    val kind: String,
    val name: String,
) {
    companion object {
        private val nativeName = Regex("[a-z][a-z0-9_]*")
        private val assetSegment = Regex("[A-Za-z0-9_-][A-Za-z0-9_.-]*")

        fun parse(
            value: String,
            kinds: Set<String>,
        ): Result<ResourceReference> =
            runCatching {
                require(value.startsWith('@') && '/' in value) { "Invalid resource reference" }
                val kind = value.drop(1).substringBefore('/')
                val name = value.substringAfter('/')
                require(kind in kinds) { "Unsupported resource kind: $kind" }
                val valid =
                    if (kind == "asset") {
                        name.split('/').all { assetSegment.matches(it) }
                    } else {
                        nativeName.matches(name)
                    }
                require(valid) { "Invalid resource name: $name" }
                ResourceReference(kind, name)
            }
    }
}
