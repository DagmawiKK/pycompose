import com.diffplug.gradle.spotless.SpotlessExtension
import io.gitlab.arturbosch.detekt.extensions.DetektExtension
import org.gradle.api.tasks.testing.Test

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.jvm) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.chaquopy) apply false
    alias(libs.plugins.spotless)
    alias(libs.plugins.detekt)
}

subprojects {
    apply(plugin = "com.diffplug.spotless")
    apply(plugin = "io.gitlab.arturbosch.detekt")
    configure<SpotlessExtension> {
        kotlin {
            target("src/**/*.kt")
            targetExclude("**/generated/**")
            ktlint("1.3.1")
        }
        kotlinGradle {
            target("*.gradle.kts")
            ktlint("1.3.1")
        }
    }
    configure<DetektExtension> {
        buildUponDefaultConfig = true
        config.setFrom(rootProject.files("config/detekt.yml"))
        source.setFrom(files("src/main/kotlin", "src/test/kotlin"))
    }
    tasks.withType<io.gitlab.arturbosch.detekt.Detekt>().configureEach {
        exclude("**/generated/**")
    }
    tasks.withType<Test>().configureEach {
        useJUnitPlatform()
    }
}

spotless {
    kotlin {
        target("architecture/src/**/*.kt")
        ktlint("1.3.1")
    }
    kotlinGradle {
        target("*.gradle.kts")
        ktlint("1.3.1")
    }
}

detekt {
    buildUponDefaultConfig = true
    config.setFrom(files("config/detekt.yml"))
    source.setFrom(files("architecture/src/test/kotlin"))
}

tasks.register("testDebugUnitTest") {
    dependsOn(":ir:test", ":host:testDebugUnitTest", ":renderer:testDebugUnitTest")
}
