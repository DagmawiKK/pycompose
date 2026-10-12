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
    }
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
    testImplementation(libs.junit.jupiter)
    testImplementation(libs.archunit)
    testRuntimeOnly(libs.junit.platform.launcher)
}
