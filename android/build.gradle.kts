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

// Not a module: a task that reads :renderer's resolved classpath and writes the
// Compose API as JSON for the schema tooling. Applied, not included, because it
// is a build-time utility and nothing should depend on it -- and it must live
// here rather than in settings.gradle.kts because it needs a project receiver.
apply(from = "dump-compose-api.gradle.kts")

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
