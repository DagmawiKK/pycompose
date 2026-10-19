import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import org.gradle.process.ExecOperations
import java.security.MessageDigest
import javax.inject.Inject

interface ProcessServices {
    @get:Inject
    val operations: ExecOperations
}

val processServices = objects.newInstance<ProcessServices>()

// Development-only evidence: pinned Compose sources, compiled to typed defaults.
// Neither this compiler nor its output ships; see tools/SourceDefaults.kt.
val sourceCompiler = configurations.create("composeSourceCompiler")

dependencies {
    add(sourceCompiler.name, "org.jetbrains.kotlin:kotlin-compiler-embeddable:2.4.21")
    add(sourceCompiler.name, "com.google.code.gson:gson:2.11.0")
}

/** Digest of every tool source: the staleness contract covers both halves. */
fun toolHash(tools: List<File>): String {
    val digest = MessageDigest.getInstance("SHA-256")
    tools.forEach { digest.update(it.readBytes()) }
    return digest.digest().joinToString("") { "%02x".format(it) }
}

fun hex(bytes: ByteArray): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
    return digest.joinToString("") { "%02x".format(it) }
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
    val schema = rootProject.file("../schema/components.json")
    val tools =
        rootProject
            .file("tools")
            .listFiles()!!
            .filter { it.extension == "kt" }
            .sortedBy { it.name }
    val output = layout.buildDirectory.dir("compose-api")
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
    inputs.files(tools)
    inputs.files(sourceCompiler)

    // Artifact, source and compiler inputs are revalidated on every invocation.
    doLast {
        val directory = output.get().asFile
        val inventoryFile = File(directory, "inventory.json")
        val inventory = JsonSlurper().parse(inventoryFile) as Map<String, Any>

        @Suppress("UNCHECKED_CAST")
        val records = inventory["declarations"] as List<Map<String, Any?>>
        val requested = names.get().split(',').toSet()
        val identities = sources.get().split(',').toSet()
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
                record["disposition"] == "ui" ||
                    supported &&
                    (named || constructed || identities.contains(identity))
            }
        check(targets.isNotEmpty()) { "No matching public declarations" }

        val sources = targets.map { it["artifact"].toString() }.toSortedSet()
        val archives =
            sources.map { coordinate ->
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
                    "sha256" to hex(file.readBytes()),
                )
            }

        val unpacked = File(directory, "source-classpath")
        unpacked.mkdirs()
        val runtime =
            project(":renderer")
                .configurations
                .getByName("debugCompileClasspath")
                .files
        val nativeClasspath =
            runtime.mapNotNull { file ->
                if (file.extension != "aar") {
                    file
                } else {
                    val jar = File(unpacked, file.nameWithoutExtension + ".jar")
                    val hasClasses =
                        java.util.zip.ZipFile(file).use { zip ->
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

        val request = File(directory, "source-request.json")
        request.writeText(
            JsonOutput.toJson(
                mapOf(
                    "toolHash" to toolHash(tools),
                    "inventoryHash" to hex(inventoryFile.readBytes()),
                    "sources" to archives,
                    "targets" to targets,
                    "classpath" to nativeClasspath.map { it.absolutePath },
                    "compilerClasspath" to sourceCompiler.files.map { it.absolutePath },
                    "javaExecutable" to
                        File(System.getProperty("java.home"), "bin/java").absolutePath,
                ),
            ),
        )

        val compiled = File(directory, "source-tool")
        processServices.operations
            .javaexec {
                classpath = sourceCompiler
                mainClass.set("org.jetbrains.kotlin.cli.jvm.K2JVMCompiler")
                args(
                    "-no-stdlib",
                    "-no-reflect",
                    "-classpath",
                    sourceCompiler.asPath,
                    "-d",
                    compiled.absolutePath,
                    *tools.map { it.absolutePath }.toTypedArray(),
                )
            }.assertNormalExitValue()

        val defaults = File(directory, "defaults.json")
        processServices.operations
            .javaexec {
                classpath = sourceCompiler + files(compiled)
                mainClass.set("SourceDefaultsKt")
                maxHeapSize = "3g"
                args(request.absolutePath, defaults.absolutePath)
            }.assertNormalExitValue()
    }
}
