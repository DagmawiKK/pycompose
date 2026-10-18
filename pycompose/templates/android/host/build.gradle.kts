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
            "\"${providers.gradleProperty("pycomposeEntrypoint").getOrElse("main:app")}\"",
        )
    }
    testOptions.unitTests.isIncludeAndroidResources = true
    bundle.language.enableSplit = false
    // The app's generated component slice (ADR-0014); see ir/build.gradle.kts.
    sourceSets
        .getByName("main")
        .kotlin
        .srcDir(rootProject.file(".pycompose/generated/host/src/main/kotlin"))
    sourceSets.getByName("main").manifest.srcFile(
        providers.gradleProperty("pycomposeManifest").getOrElse("src/main/AndroidManifest.xml"),
    )
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
        // App requirements arrive as newline-separated data from
        // pycompose.toml; the app never edits this file to add a package.
        val requirements =
            providers
                .gradleProperty("pycomposeRequirements")
                .orNull
                ?.lines()
                ?.filter(String::isNotBlank)
                .orEmpty()
        if (requirements.isNotEmpty()) {
            pip {
                requirements.forEach { install(it) }
            }
        }
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

// True when the app imports its own generated slice (ADR-0014); `pycompose
// build` sets the property. A raw Gradle build keeps the library catalog,
// which is what the fallback sample under src/main/python imports.
val ownSlice = providers.gradleProperty("pycomposeOwnSlice").orNull == "true"
val integrationModules =
    providers
        .gradleProperty("pycomposeIntegrationModules")
        .orNull
        ?.lines()
        ?.filter(String::isNotBlank)
        ?.toSet()
        .orEmpty()

val stageRuntime by tasks.registering(Sync::class) {
    from(providers.gradleProperty("pycomposeRuntimeDir").getOrElse(rootProject.file("..").path)) {
        include("pycompose/**/*.py", "pycompose/py.typed")
        exclude("pycompose/cli/**", "pycompose/templates/**", "pycompose/testing/**")
        // Reference recipes are ordinary opt-in consumers of the extension contract.
        // Metadata and planning tools never belong in an application runtime.
        exclude("pycompose/extensions/definition.py")
        exclude {
            it.path.startsWith("pycompose/integrations/") &&
                it.name != "__init__.py" &&
                it.name.removeSuffix(".py") !in integrationModules
        }
        // The app's own slice is the only copy of the catalog's components it
        // carries; shipping pycompose/m3 too would put every component back
        // into the APK the slice exists to keep out.
        if (ownSlice) {
            exclude("pycompose/m3/**")
        }
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
