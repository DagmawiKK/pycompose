package com.pycompose.architecture

import com.tngtech.archunit.core.domain.JavaClass
import com.tngtech.archunit.core.importer.ClassFileImporter
import com.tngtech.archunit.core.importer.ImportOption
import com.tngtech.archunit.lang.ArchCondition
import com.tngtech.archunit.lang.ConditionEvents
import com.tngtech.archunit.lang.SimpleConditionEvent
import com.tngtech.archunit.lang.syntax.ArchRuleDefinition.classes
import com.tngtech.archunit.lang.syntax.ArchRuleDefinition.noClasses
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

class ArchitectureTest {
    private val imported =
        ClassFileImporter()
            .withImportOption(ImportOption.DoNotIncludeTests())
            .importPackages("com.pycompose")

    @Test
    fun `ir is a nonempty pure JVM contract`() {
        assertTrue(imported.any { it.packageName.startsWith("com.pycompose.ir") })
        noClasses()
            .that()
            .resideInAPackage("com.pycompose.ir..")
            .should()
            .dependOnClassesThat()
            .resideInAnyPackage(
                "android..",
                "androidx..",
                "com.chaquo..",
            ).check(imported)
    }

    @Test
    fun `Python namespace never leaks into Kotlin`() {
        noClasses()
            .should()
            .dependOnClassesThat()
            .resideInAPackage("pycompose..")
            .check(imported)
    }

    @Test
    fun `Chaquopy stays in host bridge`() {
        noClasses()
            .that()
            .resideOutsideOfPackage("com.pycompose.host.bridge..")
            .should()
            .dependOnClassesThat()
            .resideInAPackage("com.chaquo.python..")
            .check(imported)
    }

    @Test
    fun `renderer remains independent of host and reflection`() {
        classes().should(boundaryCondition()).check(imported)
    }

    private fun boundaryCondition(): ArchCondition<JavaClass> =
        object : ArchCondition<JavaClass>("respect renderer and bridge dependency boundaries") {
            override fun check(item: JavaClass, events: ConditionEvents) {
                val renderer = item.packageName.startsWith("com.pycompose.renderer")
                val bridge = item.packageName.startsWith("com.pycompose.host.bridge")
                item.directDependenciesFromSelf.forEach { dependency ->
                    val target = dependency.targetClass.name
                    val reflection =
                        target.startsWith("java.lang.reflect.") ||
                            target.startsWith("kotlin.reflect.")
                    val forbidden =
                        renderer &&
                            target.startsWith("com.pycompose.host.") ||
                            (renderer || bridge) &&
                            reflection
                    if (forbidden) {
                        events.add(SimpleConditionEvent.violated(item, dependency.description))
                    }
                }
            }
        }
}
