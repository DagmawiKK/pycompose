plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(libs.serialization.json)
    testImplementation(libs.junit.jupiter)
    testRuntimeOnly(libs.junit.platform.launcher)
}

// The language the host evaluates within a frame knows no Android, Compose or
// catalog: whoever runs it hands it the limits and the streams to read.
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
                ":program must remain pure JVM; forbidden dependency: ${artifact.moduleVersion.id}"
            }
        }
    }
}
