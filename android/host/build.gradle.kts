plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.chaquopy)
}

extensions.configure<com.android.build.api.dsl.ApplicationExtension> {
    namespace = "com.pycompose.host"
    compileSdk = 37
    defaultConfig {
        applicationId =
            providers.gradleProperty("pycomposeApplicationId").getOrElse("com.pycompose.sample")
        minSdk = 24
        targetSdk = 36
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
    sourceSets
        .getByName(
            "test",
        ).resources
        .srcDir("../../packages/pycompose-testing/src/pycompose_testing/fixtures")
    sourceSets.getByName("test").kotlin.srcDir("../architecture/src/test/kotlin")
    // Device-free rendering of an app's snapshots (`pycompose render`); it ships
    // with every generated project, unlike the library's own tests.
    sourceSets.getByName("test").kotlin.srcDir("src/render/kotlin")
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
        // `pycompose build` names the interpreter it runs on, so bytecode is
        // compiled at build time instead of on the device at first start.
        providers.gradleProperty("pycomposeBuildPython").orNull?.let { buildPython(it) }
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
        // Tool caches beside the app's source (.mypy_cache, .pytest_cache and
        // the like) and stale bytecode are never part of the app.
        exclude("**/.*", "**/.*/**", "**/__pycache__/**")
    }
}

// True when the app imports its own generated slice (ADR-0014); `pycompose
// build` sets the property. A raw Gradle build keeps the library catalog,
// which is what the fallback sample under src/main/python imports.
val ownSlice = providers.gradleProperty("pycomposeOwnSlice").orNull == "true"

val stageRuntime by tasks.registering(Sync::class) {
    from(
        providers
            .gradleProperty(
                "pycomposeRuntimeDir",
            ).getOrElse(rootProject.file("../packages/pycompose/src").path),
    ) {
        // The runtime package whole -- the command line, the catalog pipeline and
        // the test driver are other distributions, so none of them is in it
        // (ADR-0063) -- and the catalog it validates against, as data.
        include("pycompose/**/*.py", "pycompose/py.typed", "pycompose/contract/catalog.lock.json")
        // The app's own slice is the only copy of the catalog's components it
        // carries; shipping the library's component packages too (and the old
        // name forwarding to them) would put every component back into the APK
        // the slice exists to keep out.
        if (ownSlice) {
            exclude("pycompose/foundation/**", "pycompose/material3/**", "pycompose/m3/**")
        }
    }
    into(layout.buildDirectory.dir("generated/runtime"))
}
tasks.matching { it.name.matches(Regex("merge.*PythonSources")) }.configureEach {
    dependsOn(stageRuntime)
}

// `pycompose render` names its request; RenderSnapshots renders nothing without it.
// An app library built for a newer Java loads only on a JVM at least that new:
// the app's lock slice names it, and only the tests run there.
val testJvm = providers.gradleProperty("pycomposeTestJvm").orNull?.toInt()
tasks.withType<Test>().configureEach {
    if (testJvm != null && testJvm > 17) {
        javaLauncher.set(
            javaToolchains.launcherFor {
                languageVersion.set(JavaLanguageVersion.of(testJvm))
            },
        )
    }
    providers
        .gradleProperty(
            "pycomposeRender",
        ).orNull
        ?.let { systemProperty("pycompose.render", it) }
    // Recorded queue runs, checked against the protocol model by tools/spec/trace.py.
    systemProperty(
        "pycompose.traces",
        layout.buildDirectory
            .dir("traces")
            .get()
            .asFile.path,
    )
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(project(":ir"))
    implementation(project(":renderer"))
    if (rootProject.file("fragments").isDirectory) implementation(project(":fragments"))
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.material3)
    implementation(libs.compose.material3.adaptive.navigation.suite)
    implementation(libs.compose.material3.adaptive)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.compose)
    implementation(libs.lifecycle.viewmodel)
    implementation(libs.lifecycle.savedstate)
    implementation(libs.coroutines.android)
    implementation(libs.serialization.json)
    implementation(libs.tracing)
    testImplementation(libs.junit.jupiter)
    testImplementation(libs.archunit)
    testRuntimeOnly(libs.junit.platform.launcher)
    testImplementation(libs.coroutines.test)
    testImplementation(libs.compose.test)
    testImplementation(libs.robolectric)
    testImplementation(libs.junit4)
    testRuntimeOnly(libs.junit.vintage)
    debugImplementation(libs.compose.test.manifest)
    // Debug builds can show @Preview functions; the library's generated
    // catalog of every component lives in src/debug and ships with no app.
    debugImplementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.tooling)
}
