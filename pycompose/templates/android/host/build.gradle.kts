plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.chaquopy)
}

android {
    namespace = "com.pycompose.host"
    compileSdk = 35
    defaultConfig {
        applicationId =
            providers.gradleProperty("pycomposeApplicationId").getOrElse("com.pycompose.sample")
        minSdk = 24
        targetSdk = 35
        versionCode = providers.gradleProperty("pycomposeVersionCode").getOrElse("1").toInt()
        versionName = providers.gradleProperty("pycomposeVersionName").getOrElse("0.1.0")
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    defaultConfig {
        buildConfigField(
            "String",
            "PYCOMPOSE_ENTRYPOINT",
            "\"${providers.gradleProperty("pycomposeEntrypoint").getOrElse("main:build")}\"",
        )
    }
    testOptions.unitTests.isIncludeAndroidResources = true
    bundle.language.enableSplit = false
    sourceSets.getByName("test").resources.srcDir("../../pycompose/testing/fixtures")
    sourceSets.getByName("test").java.srcDir("../architecture/src/test/kotlin")
    lint {
        abortOnError = true
        warningsAsErrors = true
        // Version upgrades need compatibility testing; availability hints are informational.
        informational += listOf("OldTargetApi", "AndroidGradlePluginVersion", "GradleDependency")
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
    }
    sourceSets.getByName("main") {
        setSrcDirs(
            listOf(
                providers.gradleProperty("pycomposeSourceDir").getOrElse("src/main/python"),
                layout.buildDirectory.dir("generated/runtime"),
            ),
        )
    }
}

val stageRuntime by tasks.registering(Sync::class) {
    from(providers.gradleProperty("pycomposeRuntimeDir").getOrElse(rootProject.file("..").path)) {
        include("pycompose/**/*.py", "pycompose/py.typed")
        exclude("pycompose/cli/**", "pycompose/templates/**", "pycompose/testing/**")
    }
    into(layout.buildDirectory.dir("generated/runtime"))
}
tasks.matching { it.name.matches(Regex("merge.*PythonSources")) }.configureEach {
    dependsOn(stageRuntime)
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(project(":ir"))
    implementation(project(":renderer"))
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.material3)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.compose)
    implementation(libs.lifecycle.viewmodel)
    implementation(libs.lifecycle.savedstate)
    implementation(libs.coroutines.android)
    implementation(libs.serialization.json)
    testImplementation(libs.junit.jupiter)
    testImplementation(libs.archunit)
    testRuntimeOnly(libs.junit.platform.launcher)
    testImplementation(libs.coroutines.test)
    testImplementation(libs.compose.test)
    testImplementation(libs.robolectric)
    testImplementation(libs.junit4)
    testRuntimeOnly(libs.junit.vintage)
    debugImplementation(libs.compose.test.manifest)
}
