import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.security.MessageDigest

// Development-only evidence: pinned Compose sources, compiled to typed defaults.
// Neither this compiler nor its output ships; see tools/SourceDefaults.kt.
val sourceCompiler = configurations.create("composeSourceCompiler")

dependencies {
    add(sourceCompiler.name, "org.jetbrains.kotlin:kotlin-compiler-embeddable:2.0.21")
    add(sourceCompiler.name, "com.google.code.gson:gson:2.11.0")
}

fun hex(bytes: ByteArray): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
    return digest.joinToString("") { "%02x".format(it) }
}

/** Every approved value binding; every pinned UI overload is requested below. */
fun approvedNames(schema: File): String {
    val registry = JsonSlurper().parse(schema) as Map<*, *>
    val values = registry["valueTypes"] as Map<*, *>
    return values.entries
        .map { (name, spec) ->
            val bound = (spec as Map<*, *>?)?.containsKey("family") == true
            if (bound) name else null
        }.filterNotNull()
        .joinToString(",")
}

tasks.register("dumpComposeDefaults") {
    group = "build"
    description = "Resolve pinned source defaults as typed, non-executable evidence."
    dependsOn("dumpComposeApi")
    val schema = rootProject.file("../schema/components.json")
    val tool = rootProject.file("tools/SourceDefaults.kt")
    val output = layout.buildDirectory.dir("compose-api")
    val names =
        providers.provider {
            val override = providers.gradleProperty("composeValueNames").orNull
            override ?: approvedNames(schema)
        }
    inputs.property("names", names)
    inputs.file(schema)
    inputs.file(tool)

    // Artifact, source and compiler inputs are revalidated on every invocation.
    doLast {
        val directory = output.get().asFile
        val inventoryFile = File(directory, "inventory.json")
        val inventory = JsonSlurper().parse(inventoryFile) as Map<String, Any>

        @Suppress("UNCHECKED_CAST")
        val records = inventory["declarations"] as List<Map<String, Any?>>
        val requested = names.get().split(',').toSet()
        val targets =
            records.filter { record ->
                val owner = record["owner"].toString().substringAfterLast('.')
                val supported = record["disposition"] == "support"
                val named = requested.contains(record["name"].toString())
                val constructed = record["name"] == "<init>" && requested.contains(owner)
                record["disposition"] == "ui" || supported && (named || constructed)
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
            runtime.map { file ->
                if (file.extension != "aar") {
                    file
                } else {
                    val jar = File(unpacked, file.nameWithoutExtension + ".jar")
                    java.util.zip.ZipFile(file).use { zip ->
                        val entry = checkNotNull(zip.getEntry("classes.jar"))
                        jar.writeBytes(zip.getInputStream(entry).readBytes())
                    }
                    jar
                }
            }

        val request = File(directory, "source-request.json")
        request.writeText(
            JsonOutput.toJson(
                mapOf(
                    "toolHash" to hex(tool.readBytes()),
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
        javaexec {
            classpath = sourceCompiler
            mainClass.set("org.jetbrains.kotlin.cli.jvm.K2JVMCompiler")
            args(
                "-no-stdlib",
                "-no-reflect",
                "-classpath",
                sourceCompiler.asPath,
                "-d",
                compiled.absolutePath,
                tool.absolutePath,
            )
        }.assertNormalExitValue()

        val defaults = File(directory, "defaults.json")
        javaexec {
            classpath = sourceCompiler + files(compiled)
            mainClass.set("SourceDefaultsKt")
            maxHeapSize = "3g"
            args(request.absolutePath, defaults.absolutePath)
        }.assertNormalExitValue()
    }
}
