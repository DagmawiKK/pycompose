plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.compose)
}

extensions.configure<com.android.build.api.dsl.LibraryExtension> {
    namespace = "com.pycompose.renderer"
    compileSdk = 37
    defaultConfig {
        minSdk = 24
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
    }
    testOptions.unitTests.isIncludeAndroidResources = true
    // The app's generated component slice (ADR-0014); see ir/build.gradle.kts.
    sourceSets
        .getByName("main")
        .kotlin
        .srcDir(rootProject.file(".pycompose/generated/renderer/src/main/kotlin"))
    sourceSets.getByName("test").kotlin.srcDir("../architecture/src/test/kotlin")
    sourceSets
        .getByName(
            "test",
        ).resources
        .srcDir("../../packages/pycompose/src/pycompose/testing/fixtures")
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    api(project(":ir"))
    api(libs.serialization.json)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.runtime)
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    // PropResolver.textStyle reads MaterialTheme, so :renderer needs material3.
    // It had no reason to before: no adapter generated a style from the wire.
    implementation(libs.compose.material3)
    // The icon vocabulary resolves to `Icons.<Style>.<Name>` properties, which
    // material3 does not put on the compile classpath.
    implementation(libs.compose.material.icons.core)
    // The completion release's integration domains. They have to resolve on the
    // extraction classpath so dumpComposeApi can account for every ratified
    // app-facing group, and the renderer binds them as each domain lands.
    // Testing/tooling artifacts never ride this classpath.
    implementation(libs.activity.compose)
    implementation(libs.constraintlayout.compose)
    implementation(libs.lifecycle.compose)
    implementation(libs.lifecycle.viewmodel)
    implementation(libs.navigation.compose)
    implementation(libs.navigation3.ui)
    implementation(libs.paging.compose)
    implementation(libs.window)
    implementation(libs.compose.material3.adaptive.navigation.suite)
    implementation(libs.compose.material3.adaptive)
    // Material 2 is a design profile of its own (pycompose.m2), never a default
    // of the Material 3 namespace.
    implementation(libs.compose.material)
    // The app's own Compose libraries (`pycompose add`, plan 31 §16.3): on the
    // extraction classpath like Google's, and exposed to :host, whose generated
    // adapters call them. The library itself lists none.
    rootProject
        .file("compose-libraries.txt")
        .takeIf { it.isFile }
        ?.readLines()
        ?.filter(String::isNotBlank)
        ?.forEach { api(it) }
    testImplementation(libs.compose.test)
    testImplementation(libs.robolectric)
    testImplementation(libs.junit4)
    testImplementation(libs.junit.jupiter)
    testImplementation(libs.archunit)
    testRuntimeOnly(libs.junit.vintage)
    testRuntimeOnly(libs.junit.platform.launcher)
    debugImplementation(libs.compose.test.manifest)
}
