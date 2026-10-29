plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    jvmToolchain(17)
}

// The app's generated component slice (ADR-0014) is build output: `pycompose
// build` regenerates it into this project-level tree before Gradle runs, and
// this is the module that compiles it. The repository never creates it -- the
// committed full catalog in src/main is what the library's own tests compile.
kotlin.sourceSets
    .getByName("main")
    .kotlin
    .srcDir(rootProject.file(".pycompose/generated/ir/src/main/kotlin"))

kotlin.sourceSets
    .getByName("test")
    .kotlin
    .srcDir("../architecture/src/test/kotlin")

// The golden snapshots Python's tests also read: one copy, beside the library.
sourceSets
    .getByName(
        "test",
    ).resources
    .srcDir("../../packages/pycompose/src/pycompose/testing/fixtures")

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
