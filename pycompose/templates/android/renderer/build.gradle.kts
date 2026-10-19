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
    sourceSets.getByName("test").resources.srcDir("../../pycompose/testing/fixtures")
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
    testImplementation(libs.compose.test)
    testImplementation(libs.robolectric)
    testImplementation(libs.junit4)
    testImplementation(libs.junit.jupiter)
    testImplementation(libs.archunit)
    testRuntimeOnly(libs.junit.vintage)
    testRuntimeOnly(libs.junit.platform.launcher)
    debugImplementation(libs.compose.test.manifest)
}
