import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import org.gradle.api.artifacts.ExternalModuleDependency
import org.gradle.api.artifacts.component.ModuleComponentSelector
import org.gradle.api.attributes.Attribute
import org.gradle.api.attributes.AttributeContainer
import org.gradle.process.ExecOperations
import java.security.MessageDigest
import java.util.zip.ZipFile
import javax.inject.Inject

// Development tooling only (plan 31 S1): extract the pinned Compose API and its
// source defaults as evidence for the schema tooling. Nothing depends on this
// module and nothing ships from it; a scaffolded app has neither the module nor
// these tasks. Gradle does only what needs Gradle -- resolving :renderer's
// classpath and the pinned sources -- and hands the result to the tools in
// src/main/kotlin through a request file, so the extraction itself is plain,
// testable Kotlin.

plugins {
    alias(libs.plugins.kotlin.jvm)
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation("org.ow2.asm:asm:9.7.1")
    implementation("org.jetbrains.kotlinx:kotlinx-metadata-jvm:0.9.0")
    implementation("org.jetbrains.kotlin:kotlin-compiler-embeddable:${libs.versions.kotlin.get()}")
    implementation("com.google.code.gson:gson:2.11.0")
    // Gradle's own Groovy: the inventory keeps the exact JSON writer it always had.
    implementation("org.apache.groovy:groovy-json:4.0.32")
}

interface ProcessServices {
    @get:Inject
    val operations: ExecOperations
}

val processServices = objects.newInstance<ProcessServices>()
val renderer = evaluationDependsOn(":renderer")
val evidence = rootProject.layout.buildDirectory.dir("compose-api")
val toolClasspath = sourceSets.main.get().runtimeClasspath
val toolSources =
    file("src/main/kotlin")
        .listFiles()!!
        .filter { it.extension == "kt" }
        .sortedBy { it.name }

fun sha256(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

/** Copy variant-driving attributes so a custom configuration resolves like its source. */
fun AttributeContainer.inheritFrom(source: AttributeContainer) {
    @Suppress("UNCHECKED_CAST")
    source.keySet().forEach { key ->
        val attribute = key as Attribute<Any>
        source.getAttribute(attribute)?.let { value -> attribute(attribute, value) }
    }
}

tasks.register("dumpComposeApi") {
    group = "build"
    description = "Extract a lossless, version-proven Compose API inventory."
    // Selection comes from compose-closure.json, never from a group prefix: every
    // scanned artifact is listed there and must match its recorded digest.
    val rendererClasspath = renderer.configurations.getByName("debugCompileClasspath")
    val closureFile = rootProject.file("compose-closure.json")
    // Testing/tooling artifacts (ui-test-*, ui-tooling*) must never ride the app
    // classpath: they drag junit, hamcrest and androidx.test into it. They resolve
    // here instead -- pinned by the closure, verified and never extracted.
    val toolingClasspath =
        renderer.configurations.maybeCreate("composeToolingClasspath").apply {
            isCanBeConsumed = false
            isCanBeResolved = true
            attributes { inheritFrom(rendererClasspath.attributes) }
        }
    ((JsonSlurper().parse(closureFile) as Map<*, *>)["tooling"] as List<*>).forEach { raw ->
        val coordinate = (raw as Map<*, *>)["coordinate"].toString()
        val dependency = renderer.dependencies.create(coordinate) as ExternalModuleDependency
        // The closure pins exact artifacts: transitive graphs are not wanted here.
        dependency.isTransitive = false
        renderer.dependencies.add(toolingClasspath.name, dependency)
    }
    val output = evidence.map { it.file("inventory.json") }
    val sourceInputs =
        rootProject.fileTree(".") {
            include(
                "*.gradle.kts",
                "*/build.gradle.kts",
                "compose-extract/src/main/kotlin/*.kt",
                "gradle/libs.versions.toml",
                "gradle.properties",
            )
        }
    inputs.files(rendererClasspath)
    inputs.files(toolClasspath)
    inputs.file(closureFile)
    inputs.files(sourceInputs)
    outputs.file(output)
    doLast {
        val variants =
            rendererClasspath.incoming.artifacts.artifacts
                .associateBy { it.file.canonicalPath }

        fun resolved(artifact: ResolvedArtifact): Map<String, Any?> {
            val attributes = variants[artifact.file.canonicalPath]?.variant?.attributes
            return mapOf(
                "coordinate" to artifact.moduleVersion.id.toString(),
                "file" to artifact.file.absolutePath,
                "attributes" to
                    attributes?.keySet()?.associate {
                        it.name to attributes.getAttribute(it).toString()
                    },
            )
        }
        val bomComponent =
            rendererClasspath.incoming.resolutionResult.allComponents
                .single {
                    it.moduleVersion?.let { m ->
                        m.group == "androidx.compose" && m.name == "compose-bom"
                    } == true
                }
        val root = rootProject.projectDir
        val request = evidence.get().file("inventory-request.json").asFile
        request.parentFile.mkdirs()
        request.writeText(
            JsonOutput.toJson(
                mapOf(
                    "closure" to closureFile.absolutePath,
                    "configuration" to ":renderer:debugCompileClasspath",
                    "artifacts" to
                        rendererClasspath.resolvedConfiguration.resolvedArtifacts.map(::resolved),
                    "tooling" to
                        toolingClasspath.resolvedConfiguration.resolvedArtifacts.map(::resolved),
                    "bom" to checkNotNull(bomComponent.moduleVersion).version,
                    "bomConstraints" to
                        bomComponent.dependencies
                            .mapNotNull {
                                (it.requested as? ModuleComponentSelector)?.let { m ->
                                    "${m.group}:${m.module}" to m.version
                                }
                            }.toMap(),
                    "compiler" to libs.versions.kotlin.get(),
                    "sourceHashes" to
                        sourceInputs.files
                            .sortedBy { it.relativeTo(root).invariantSeparatorsPath }
                            .associate {
                                it.relativeTo(root).invariantSeparatorsPath to
                                    sha256(it.readBytes())
                            },
                ),
            ),
        )
        processServices.operations
            .javaexec {
                classpath = toolClasspath
                mainClass.set("InventoryKt")
                maxHeapSize = "3g"
                args(request.absolutePath, output.get().asFile.absolutePath)
            }.assertNormalExitValue()
    }
}

tasks.register("resolveCompose") {
    group = "build"
    description = "Resolve the closure's and the app's groups against the pinned BOM."
    // What the closure must pin, for the pin as it now stands: every resolved
    // artifact of its groups and of the app's own libraries (compose-libraries.txt),
    // with digests; each tooling module at the BOM's version; and every module the
    // BOM pins that something moved. pycompose add and upgrade --bom read it.
    val rendererClasspath = renderer.configurations.getByName("debugCompileClasspath")
    val closureFile = rootProject.file("compose-closure.json")
    val libraries = rootProject.file("compose-libraries.txt")
    val output = evidence.map { it.file("resolved.json") }
    inputs.files(rendererClasspath)
    inputs.files(listOf(closureFile, libraries).filter(File::isFile))
    outputs.file(output)
    doLast {
        val closure = JsonSlurper().parse(closureFile) as Map<*, *>
        val requested =
            if (libraries.isFile) libraries.readLines().filter(String::isNotBlank) else emptyList()
        val groups =
            (closure["groups"] as Map<*, *>).keys.map(Any?::toString).toSet() +
                requested.map { it.substringBefore(':') }
        val bom =
            rendererClasspath.incoming.resolutionResult.allComponents
                .single {
                    it.moduleVersion?.let { m ->
                        m.group == "androidx.compose" && m.name == "compose-bom"
                    } == true
                }
        val pinned =
            bom.dependencies
                .mapNotNull { it.requested as? ModuleComponentSelector }
                .associate { "${it.group}:${it.module}" to it.version }
        val resolved = rendererClasspath.resolvedConfiguration.resolvedArtifacts
        val conflicts =
            resolved.mapNotNull { artifact ->
                val id = artifact.moduleVersion.id
                val expected = pinned["${id.group}:${id.name}"]
                if (expected == null || expected == id.version) {
                    null
                } else {
                    mapOf(
                        "module" to "${id.group}:${id.name}",
                        "resolved" to id.version,
                        "bom" to expected,
                    )
                }
            }
        val artifacts =
            resolved
                .filter { it.moduleVersion.id.group in groups }
                .map {
                    mapOf(
                        "coordinate" to it.moduleVersion.id.toString(),
                        "sha256" to sha256(it.file.readBytes()),
                    )
                }.sortedBy { it["coordinate"] }
        // Tooling never rides the app classpath: each module resolves alone, at
        // the version the BOM now pins for it.
        val tooling =
            (closure["tooling"] as List<*>).map { raw ->
                val module = (raw as Map<*, *>)["coordinate"].toString().substringBeforeLast(':')
                val version = pinned[module] ?: raw["coordinate"].toString().substringAfterLast(':')
                val dependency = renderer.dependencies.create("$module:$version")
                val detached = renderer.configurations.detachedConfiguration(dependency)
                detached.isTransitive = false
                detached.attributes { inheritFrom(rendererClasspath.attributes) }
                mapOf(
                    "coordinate" to "$module:$version",
                    "sha256" to sha256(detached.singleFile.readBytes()),
                )
            }
        output.get().asFile.apply { parentFile.mkdirs() }.writeText(
            JsonOutput.prettyPrint(
                JsonOutput.toJson(
                    mapOf(
                        "bom" to checkNotNull(bom.moduleVersion).version,
                        "artifacts" to artifacts,
                        "tooling" to tooling,
                        "conflicts" to conflicts,
                    ),
                ),
            ),
        )
    }
}

/** Approved bindings by exact source identity, plus names bound by no source yet. */
fun approvedBindings(schema: File): Pair<List<String>, List<String>> {
    val registry = JsonSlurper().parse(schema) as Map<*, *>
    val values = registry["valueTypes"] as Map<*, *>
    val names = mutableListOf<String>()
    val sources = mutableListOf<String>()
    values.entries.forEach { (name, raw) ->
        val spec = raw as? Map<*, *> ?: return@forEach
        if (spec["family"] == null) return@forEach
        val source = spec["source"] as? Map<*, *>
        if (source == null) {
            names.add(name.toString())
        } else {
            sources.add(
                listOf("owner", "jvmName", "descriptor")
                    .joinToString("|") { source[it].toString() },
            )
        }
    }
    return names to sources
}

tasks.register("dumpComposeDefaults") {
    group = "build"
    description = "Resolve pinned source defaults as typed, non-executable evidence."
    dependsOn("dumpComposeApi")
    // The library's lock beside it, or -PpycomposeCatalog for an app's extraction.
    val schema =
        rootProject.file(
            providers.gradleProperty("pycomposeCatalog").getOrElse("../schema/catalog.lock.json"),
        )
    val bound = providers.provider { approvedBindings(schema) }
    val names =
        providers.provider {
            providers.gradleProperty("composeValueNames").orNull
                ?: bound.get().first.joinToString(",")
        }
    val sources =
        providers.provider {
            providers.gradleProperty("composeValueNames").orNull?.let { "" }
                ?: bound.get().second.joinToString(",")
        }
    inputs.property("names", names)
    inputs.property("sources", sources)
    inputs.file(schema)
    inputs.files(toolClasspath)

    // Artifact, source and compiler inputs are revalidated on every invocation.
    doLast {
        val directory = evidence.get().asFile
        val inventoryFile = File(directory, "inventory.json")
        val inventory = JsonSlurper().parse(inventoryFile) as Map<String, Any>

        @Suppress("UNCHECKED_CAST")
        val records = inventory["declarations"] as List<Map<String, Any?>>
        val requested = names.get().split(',').toSet()
        val identities = sources.get().split(',').toSet()
        // Classes a UI composable takes: their suspend members are drive evidence.
        val holders =
            records
                .filter { it["disposition"] == "ui" }
                .flatMap { it["parameters"] as List<Map<String, Any?>> }
                .map { (it["type"] as Map<*, *>)["classifier"] }
                .toSet()
        val targets =
            records.filter { record ->
                val owner = record["owner"].toString().substringAfterLast('.')
                val jvm = record["jvm"] as Map<*, *>
                val identity =
                    listOf(record["owner"], jvm["name"], jvm["descriptor"])
                        .joinToString("|")
                val supported = record["disposition"] == "support"
                val named = requested.contains(record["name"].toString())
                val constructed = record["name"] == "<init>" && requested.contains(owner)
                val receiver = (record["dispatchReceiver"] as? Map<*, *>)?.get("classifier")
                val drive = record["suspend"] == true && receiver in holders
                record["disposition"] == "ui" ||
                    supported &&
                    (named || constructed || drive || identities.contains(identity))
            }
        check(targets.isNotEmpty()) { "No matching public declarations" }

        val archives =
            targets.map { it["artifact"].toString() }.toSortedSet().map { coordinate ->
                val dependency = dependencies.create("$coordinate:sources@jar")
                val detached = configurations.detachedConfiguration(dependency)
                detached.isTransitive = false
                detached.attributes {
                    attribute(Usage.USAGE_ATTRIBUTE, objects.named(Usage.JAVA_RUNTIME))
                    attribute(Category.CATEGORY_ATTRIBUTE, objects.named(Category.LIBRARY))
                }
                val file = detached.singleFile
                mapOf(
                    "artifact" to coordinate,
                    "file" to file.absolutePath,
                    "sha256" to sha256(file.readBytes()),
                )
            }

        val unpacked = File(directory, "source-classpath")
        unpacked.mkdirs()
        val runtime = renderer.configurations.getByName("debugCompileClasspath").files
        val nativeClasspath =
            runtime.mapNotNull { file ->
                if (file.extension != "aar") {
                    file
                } else {
                    val jar = File(unpacked, file.nameWithoutExtension + ".jar")
                    val hasClasses =
                        ZipFile(file).use { zip ->
                            val entry = zip.getEntry("classes.jar")
                            if (entry == null) {
                                check(
                                    zip.entries().toList().all {
                                        it.isDirectory ||
                                            it.name == "AndroidManifest.xml"
                                    },
                                ) {
                                    "Missing classes.jar in nonempty AAR: $file"
                                }
                                logger.lifecycle("No bytecode in manifest-only AAR: $file")
                                false
                            } else {
                                jar.writeBytes(zip.getInputStream(entry).readBytes())
                                true
                            }
                        }
                    if (hasClasses) jar else null
                }
            }

        // Digest of every tool source: the staleness contract covers both halves.
        val toolHash = MessageDigest.getInstance("SHA-256")
        toolSources.forEach { toolHash.update(it.readBytes()) }
        val request = File(directory, "source-request.json")
        request.writeText(
            JsonOutput.toJson(
                mapOf(
                    "toolHash" to toolHash.digest().joinToString("") { "%02x".format(it) },
                    "inventoryHash" to sha256(inventoryFile.readBytes()),
                    "sources" to archives,
                    "targets" to targets,
                    "classpath" to nativeClasspath.map { it.absolutePath },
                    // The tools and the compiler they embed, so tests can rerun either.
                    "compilerClasspath" to toolClasspath.files.map { it.absolutePath },
                    "javaExecutable" to
                        File(System.getProperty("java.home"), "bin/java").absolutePath,
                ),
            ),
        )
        processServices.operations
            .javaexec {
                classpath = toolClasspath
                mainClass.set("SourceDefaultsKt")
                maxHeapSize = "3g"
                args(request.absolutePath, File(directory, "defaults.json").absolutePath)
            }.assertNormalExitValue()
    }
}
