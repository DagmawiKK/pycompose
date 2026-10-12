plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    jvmToolchain(17)
}

kotlin.sourceSets
    .getByName("test")
    .kotlin
    .srcDir("../architecture/src/test/kotlin")

dependencies {
    implementation(libs.serialization.json)
    testImplementation(libs.junit.jupiter)
    testImplementation(libs.archunit)
    testRuntimeOnly(libs.junit.platform.launcher)
}

configurations.matching { it.name in setOf("compileClasspath", "runtimeClasspath") }.all {
    incoming.afterResolve {
        resolvedConfiguration.resolvedArtifacts.forEach { artifact ->
            val group = artifact.moduleVersion.id.group
            val stdlibAnnotations = group == "org.jetbrains" && artifact.name == "annotations"
            val stdlib =
                group == "org.jetbrains.kotlin" && artifact.name.startsWith("kotlin-stdlib")
            val serialization =
                group == "org.jetbrains.kotlinx" &&
                    artifact.name.startsWith("kotlinx-serialization-")
            check(stdlib || serialization || stdlibAnnotations) {
                ":ir must remain pure JVM; forbidden dependency: ${artifact.moduleVersion.id}"
            }
        }
    }
}
