import com.diffplug.gradle.spotless.SpotlessExtension
import io.gitlab.arturbosch.detekt.extensions.DetektExtension
import org.gradle.api.tasks.testing.Test

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
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
            // Generated code has exactly one owner, and it is not ktlint. Were
            // spotless to reformat it, `gen.py --check` would fail forever on a
            // file nobody is allowed to hand-edit -- the two gates would each
            // revert the other. Same reasoning as the `generated/` packages.
            // Both patterns in one call: a second targetExclude replaces the
            // first rather than adding to it, silently un-excluding `generated/`.
            targetExclude("**/generated/**", "**/Generated*.kt")
            val format = ktlint("1.3.1")
            if (path == ":compose-extract") {
                // Detekt enforces 100 columns; ktlint 1.3.1 fails to converge on
                // this compiler AST code.
                format.editorConfigOverride(mapOf("ktlint_standard_max-line-length" to "disabled"))
            }
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
        // Generated Kotlin is formatted by its generator, not by ktlint, so
        // detekt's line-length rule has nothing useful to say about it.
        exclude("**/Generated*.kt")
    }
    tasks.withType<Test>().configureEach {
        useJUnitPlatform()
    }
}

spotless {
    kotlin {
        target("architecture/src/**/*.kt")
        // Detekt enforces 100 columns; ktlint 1.3.1 fails to converge on long test lines.
        ktlint("1.3.1").editorConfigOverride(mapOf("ktlint_standard_max-line-length" to "disabled"))
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
