package com.pycompose.ir

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ResourceIrTest {
    @Test fun `resource golden is accepted only under its versioned envelope`() {
        val source = checkNotNull(javaClass.getResource("/resource_screen.json")).readText()
        assertTrue(IrParser().parse(source).isSuccess)
        assertTrue(IrParser().parse(source.replace("1.1.0", "1.0.0")).isFailure)
        val unsafe = source.replace("@drawable/ic_pycompose", "@asset/../secret")
        assertTrue(IrParser().parse(unsafe).isFailure)
        assertFalse(ResourceReference.parse("@string/bad/name", setOf("string")).isSuccess)
    }
}
