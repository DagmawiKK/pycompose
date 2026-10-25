import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.zip.ZipFile

// Development tooling only. Read the actual Android variant, never a separately
// resolved desktop/stub artifact or AndroidX main. The runtime uses no metadata.

internal const val COMPOSE_ANNOTATION = "androidx/compose/runtime/Composable"
private const val FORMAT_VERSION = 1

/** How many target errors a failed extraction lists before truncating. */
private const val REPORTED_ERRORS = 20

/** One artifact Gradle resolved: coordinate, file and variant attributes. */
private class Resolved(
    val coordinate: String,
    val file: File,
    val attributes: Map<String, String>?,
) {
    val group: String get() = coordinate.substringBefore(':')

    companion object {
        @Suppress("UNCHECKED_CAST")
        fun of(raw: Any?): Resolved {
            val entry = raw as Map<String, Any?>
            return Resolved(
                entry["coordinate"].toString(),
                File(entry["file"].toString()),
                entry["attributes"] as Map<String, String>?,
            )
        }
    }
}

/**
 * Extract a lossless, version-proven Compose API inventory.
 *
 * Gradle resolves `:renderer`'s classpath and writes what it resolved to a request
 * file (`compose-extract/build.gradle.kts`); everything else happens here, where it
 * can be tested: closure verification, extraction and the inventory document.
 */
fun main(args: Array<String>) {
    val request = JsonSlurper().parse(File(args[0])) as Map<*, *>
    val target = File(args[1])
    val closure = ComposeClosure.read(File(request["closure"].toString()))
    val resolved = (request["artifacts"] as List<*>).map(Resolved::of)
    verifyTooling(closure, (request["tooling"] as List<*>).map(Resolved::of), resolved)
    verifySupport(closure, resolved)
    val scanned = extracted(closure, resolved).map { scan(closure, it) }
    val diagnostics = mutableListOf<Map<String, Any?>>()
    val valueClasses =
        scanned
            .flatMap { valueClassAbi(it.classes).entries }
            .associate { it.toPair() }
    val apis =
        scanned.map {
            val components = closure.hasComponents(it.coordinate.substringBefore(':'))
            ApiExtractor(it.coordinate, components, diagnostics, valueClasses).extract(it.classes)
        }
    val declarations = apis.flatMap { it.declarations }
    val provenance = provenance(request, scanned.map { it.record })
    write(
        target,
        mapOf(
            "formatVersion" to FORMAT_VERSION,
            "provenance" to provenance,
            "artifacts" to scanned.map { it.record },
            "declarations" to declarations.sortedBy { "${it["owner"]}:${it["name"]}:${it["jvm"]}" },
            "classes" to
                apis.flatMap { it.classes }.sortedBy { "${it["owner"]}:${it["classKind"]}" },
            "diagnostics" to diagnostics.sortedBy { it["message"].toString() },
            "bytecodeAudit" to
                mapOf(
                    "unmatchedTargetMethods" to
                        diagnostics.filter {
                            it["target"] == true && it["unmatchedBytecode"] == true
                        },
                ),
        ),
    )
    val ui = declarations.count { it["disposition"] == "ui" }
    println(
        "dumpComposeApi: $ui public component overloads, ${declarations.size} declarations, " +
            "${diagnostics.size} extraction errors -> $target",
    )
    val targetErrors = diagnostics.filter { it["target"] == true }
    check(targetErrors.isEmpty()) {
        targetErrors.take(REPORTED_ERRORS).joinToString("\n", "Compose extraction failed:\n")
    }
    check((provenance["overrides"] as List<*>).isEmpty()) {
        "Compose BOM overrides: ${provenance["overrides"]}"
    }
    check(ui > 0) { "The resolved classpath contains no public components." }
}

/** One extracted artifact: its inventory record and its classes. */
private class Scanned(
    val coordinate: String,
    val record: Map<String, Any?>,
    val classes: Map<String, ClassApi>,
)

/** Read one closure artifact after proving its bytes are the pinned ones. */
private fun scan(closure: ComposeClosure, artifact: Resolved): Scanned {
    val coordinate = artifact.coordinate
    val bytes = artifact.file.readBytes()
    val expected = closure.artifacts.getValue(coordinate)
    val actual = sha256(bytes)
    check(actual == expected) {
        "Compose closure digest changed for $coordinate: expected $expected, got $actual"
    }
    val attributes = checkNotNull(artifact.attributes) { "$coordinate has no variant" }
    val classes =
        if (artifact.file.extension == "aar") {
            ZipFile(artifact.file).use { zip ->
                val entry =
                    checkNotNull(zip.getEntry("classes.jar")) { "$coordinate lacks classes.jar" }
                zip.getInputStream(entry).readBytes()
            }
        } else {
            bytes
        }
    return Scanned(
        coordinate,
        mapOf(
            "coordinate" to coordinate,
            "sha256" to actual,
            "variant" to attributes["org.jetbrains.kotlin.platform.type"],
            "attributes" to attributes.toSortedMap(),
            "file" to artifact.file.name,
        ),
        readClasses(classes),
    )
}

/** Where the evidence came from, and every BOM constraint the resolution broke. */
private fun provenance(request: Map<*, *>, artifacts: List<Map<String, Any?>>): Map<String, Any?> {
    @Suppress("UNCHECKED_CAST")
    val bomConstraints = (request["bomConstraints"] as Map<String, String>).toSortedMap()
    val overrides =
        artifacts.mapNotNull {
            val coordinate = it["coordinate"].toString()
            val module = coordinate.substringBeforeLast(':')
            val expected = bomConstraints[module]
            val version = coordinate.substringAfterLast(':')
            if (expected != null &&
                expected != version
            ) {
                "$module expected $expected, resolved $version"
            } else {
                null
            }
        }
    return mapOf(
        "configuration" to request["configuration"],
        "bom" to request["bom"],
        "compiler" to request["compiler"],
        "bomConstraints" to bomConstraints,
        "overrides" to overrides,
        "sourceHashes" to request["sourceHashes"],
    )
}

/** Replace the inventory atomically, so a failed run never leaves half a file. */
private fun write(target: File, document: Map<String, Any?>) {
    target.parentFile.mkdirs()
    val temporary = File(target.parentFile, "inventory.json.pending")
    temporary.writeText(JsonOutput.toJson(document) + "\n")
    Files.move(
        temporary.toPath(),
        target.toPath(),
        StandardCopyOption.REPLACE_EXISTING,
        StandardCopyOption.ATOMIC_MOVE,
    )
}

/**
 * Testing/tooling artifacts resolve on their own configuration: pinned by the
 * closure, verified and never extracted.
 */
private fun verifyTooling(
    closure: ComposeClosure,
    tooling: List<Resolved>,
    resolved: List<Resolved>,
) {
    val coordinates = tooling.map { it.coordinate }.toSet()
    val missing = (closure.tooling.keys - coordinates).sorted()
    check(missing.isEmpty()) {
        "Compose closure file expects tooling artifacts that are not resolved: " +
            missing.joinToString(", ")
    }
    val unexpected = (coordinates - closure.tooling.keys).sorted()
    check(unexpected.isEmpty()) {
        "Compose tooling configuration resolved unpinned artifacts: " +
            unexpected.joinToString(", ")
    }
    tooling.forEach { artifact ->
        val expected = closure.tooling.getValue(artifact.coordinate)
        val actual = sha256(artifact.file.readBytes())
        check(actual == expected) {
            "Compose closure tooling digest changed for ${artifact.coordinate}: " +
                "expected $expected, got $actual"
        }
    }
    val onAppClasspath = resolved.map { it.coordinate }.filter { it in closure.tooling }.sorted()
    if (onAppClasspath.isNotEmpty()) {
        println(
            "dumpComposeApi: tooling artifacts also resolve on the extraction classpath " +
                "(not extracted): ${onAppClasspath.joinToString(", ")}",
        )
    }
}

/**
 * Support artifacts sit inside extracted groups but carry no Android app surface:
 * pin their bytes, prove they resolve, and never scan them.
 */
private fun verifySupport(closure: ComposeClosure, resolved: List<Resolved>) {
    val coordinates = resolved.map { it.coordinate }.toSet()
    val missing = (closure.support.keys - coordinates).sorted()
    check(missing.isEmpty()) {
        "Compose closure file expects support artifacts that are not resolved: " +
            missing.joinToString(", ")
    }
    val support = resolved.filter { it.coordinate in closure.support }
    support.forEach { artifact ->
        val expected = closure.support.getValue(artifact.coordinate)
        val actual = sha256(artifact.file.readBytes())
        check(actual == expected) {
            "Compose closure support digest changed for ${artifact.coordinate}: " +
                "expected $expected, got $actual"
        }
    }
    if (support.isNotEmpty()) {
        println(
            "dumpComposeApi: support artifacts of extracted groups are not extracted: " +
                support.map { it.coordinate }.sorted().joinToString(", "),
        )
    }
}

/** The artifacts to scan: exactly the closure's, after proving nothing else hides. */
private fun extracted(closure: ComposeClosure, resolved: List<Resolved>): List<Resolved> {
    val coordinates = resolved.map { it.coordinate }.toSet()
    val missing = (closure.artifacts.keys - coordinates).sorted()
    check(missing.isEmpty()) {
        "Compose closure file expects artifacts that are not resolved: ${missing.joinToString(
            ", ",
        )}"
    }
    val unexpected =
        resolved
            .filter {
                closure.statusOf(it.group) == "extracted" &&
                    it.coordinate !in closure.artifacts &&
                    it.coordinate !in closure.tooling &&
                    it.coordinate !in closure.support
            }.map { it.coordinate }
            .sorted()
    check(unexpected.isEmpty()) {
        "Compose closure file is missing resolved artifacts of extracted groups: " +
            unexpected.joinToString(", ")
    }
    val pending = resolved.filter { closure.statusOf(it.group) == "pending" }
    if (pending.isNotEmpty()) {
        val summary =
            pending
                .groupBy { it.group }
                .toSortedMap()
                .map { (group, artifacts) -> "$group (${artifacts.size})" }
                .joinToString(", ")
        println(
            "dumpComposeApi: resolved artifacts of pending closure groups are not " +
                "extracted yet: $summary",
        )
    }
    return resolved.filter { it.coordinate in closure.artifacts }.sortedBy { it.coordinate }
}

private fun sha256(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

/** The checked-in extraction closure: group policy plus the pinned artifact digests. */
private class ComposeClosure(
    private val groupStatus: Map<String, String>,
    private val componentGroups: Set<String>,
    val artifacts: Map<String, String>,
    val tooling: Map<String, String>,
    val support: Map<String, String>,
) {
    fun statusOf(group: String): String? = groupStatus[group]

    fun hasComponents(group: String): Boolean = group in componentGroups

    companion object {
        fun read(file: File): ComposeClosure {
            val document = JsonSlurper().parse(file) as Map<*, *>
            check(
                document["schema"] == 1,
            ) { "Unsupported compose closure schema: ${document["schema"]}" }
            val groups = LinkedHashMap<String, String>()
            val componentGroups = mutableSetOf<String>()
            (document["groups"] as Map<*, *>).forEach { (name, raw) ->
                groups[name.toString()] = (raw as Map<*, *>)["status"].toString()
                if (raw["components"] == true) componentGroups.add(name.toString())
            }
            val artifacts = digestsOf(document["artifacts"] as List<*>)
            val tooling = digestsOf(document["tooling"] as List<*>)
            val support = digestsOf(document["support"] as List<*>)
            val overlap =
                (support.keys intersect artifacts.keys) + (support.keys intersect tooling.keys)
            check(overlap.isEmpty()) {
                "Compose closure support artifacts are also extracted or tooling: " +
                    overlap.sorted().joinToString(", ")
            }
            return ComposeClosure(groups, componentGroups, artifacts, tooling, support)
        }

        private fun digestsOf(entries: List<*>): Map<String, String> {
            val digests = LinkedHashMap<String, String>()
            entries.forEach { raw ->
                val entry = raw as Map<*, *>
                digests[entry["coordinate"].toString()] = entry["sha256"].toString()
            }
            return digests
        }
    }
}
