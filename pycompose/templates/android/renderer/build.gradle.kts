plugins {
    alias(libs.plugins.android.library)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.pycompose.renderer"
    compileSdk = 35
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
    sourceSets.getByName("test").java.srcDir("../architecture/src/test/kotlin")
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
    testImplementation(libs.compose.test)
    testImplementation(libs.robolectric)
    testImplementation(libs.junit4)
    testImplementation(libs.junit.jupiter)
    testImplementation(libs.archunit)
    testRuntimeOnly(libs.junit.vintage)
    testRuntimeOnly(libs.junit.platform.launcher)
    debugImplementation(libs.compose.test.manifest)
}
