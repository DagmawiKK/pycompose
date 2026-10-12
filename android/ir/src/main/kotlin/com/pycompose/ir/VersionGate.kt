package com.pycompose.ir

import com.pycompose.ir.generated.IrContract
import java.math.BigInteger

internal object VersionGate {
    private val syntax = Regex("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)")

    private fun parts(
        value: String,
        field: String,
    ): List<BigInteger> {
        require(syntax.matches(value)) { "$field must be MAJOR.MINOR.PATCH: $value" }
        return value.split('.').map(::BigInteger)
    }

    private fun compare(
        left: List<BigInteger>,
        right: List<BigInteger>,
    ): Int = left.zip(right).firstOrNull { (a, b) -> a != b }?.let { (a, b) -> a.compareTo(b) } ?: 0

    fun check(
        schema: String,
        library: String,
        minimum: String,
    ) {
        val candidate = parts(schema, "schemaVersion")
        require(compare(candidate, parts(minimum, "minSchemaVersion")) >= 0) {
            "schemaVersion $schema is below host minSchemaVersion $minimum"
        }
        require(candidate == parts(IrContract.SCHEMA_VERSION, "supported schemaVersion")) {
            "Unsupported schemaVersion $schema; host supports ${IrContract.SCHEMA_VERSION}"
        }
        require(
            compare(
                parts(library, "version"),
                parts(IrContract.MIN_LIBRARY_VERSION, "minLibraryVersion"),
            ) >=
                0,
        ) {
            "Library version $library is below ${IrContract.MIN_LIBRARY_VERSION}"
        }
    }
}
