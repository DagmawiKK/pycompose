import java.io.ByteArrayInputStream
import java.util.zip.ZipFile
import java.util.zip.ZipInputStream

// Dump the resolved Compose classpath's real public API.
//
// This is the replacement for reading AndroidX's published `current.txt`, which
// was blocked: every `androidx-*-stable` tag 404s, and `androidx-main` is ahead
// of the BOM this project pins -- main declares `TextFieldState` from material3
// 1.4.0-alpha while the BOM here resolves material3 to 1.3.1. Generating a
// catalog from main produces components the pinned Compose cannot compile.
//
// Reading the classpath the app actually resolves removes the version question
// entirely. There is no second version to keep in step, because the classpath
// *is* the version.
//
// It is applied to the main build and reads :renderer's compile classpath rather
// than resolving its own. A standalone project resolves the `-desktop` and
// `-jvmstubs` variants of the same versions -- different artifacts, different
// signatures -- so "the version we pin" and "the artifact we link" would quietly
// diverge, which is the failure this whole approach exists to remove.
//
// Applied as a script plugin so this stays out of build.gradle.kts, and never on
// an app's build path.

buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        // ASM reads the classfile: which methods carry @Composable, and their
        // real JVM parameter types. kotlinx-metadata decodes the @Metadata blob
        // Kotlin embeds, which is the only place the Kotlin-level parameter
        // *names* live.
        classpath("org.ow2.asm:asm:9.7.1")
        classpath("org.jetbrains.kotlinx:kotlinx-metadata-jvm:0.9.0")
        // kotlin.Metadata, which the blob is reconstructed into. Not inherited
        // transitively into a buildscript classpath.
        classpath("org.jetbrains.kotlin:kotlin-stdlib:1.9.23")
    }
}

val composableDescriptor = "Landroidx/compose/runtime/Composable;"
val metadataDescriptor = "Lkotlin/Metadata;"
val asm9 = org.objectweb.asm.Opcodes.ASM9
val classesJar = "classes.jar"

val renderer = project(":renderer")

// Counted rather than logged per class: a systemic failure would otherwise
// print once per composable and bury the summary, while a partial one is worth
// seeing at all.
var metadataFailures = 0

tasks.register("dumpComposeApi") {
    group = "build"
    description = "Write the resolved Compose classpath's public API as JSON."

    val classpath = renderer.configurations.getByName("debugCompileClasspath")
    val outDir = layout.buildDirectory.dir("compose-api")
    inputs.files(classpath)
    outputs.dir(outDir)

    doLast {
        val target = outDir.get().asFile
        target.mkdirs()
        var artifacts = 0
        var composables = 0
        classpath.resolve().forEach { url ->
            val path = url.toString()
            // AndroidX ships AARs, and every Compose artifact on this classpath
            // is one. Filtering to `.jar` alone silently drops the entire library
            // and reports zero composables -- which reads exactly like a Compose
            // that declares nothing.
            if (!path.endsWith(".jar") && !path.endsWith(".aar")) return@forEach
            val file = file(url.toURI())
            // Sources carry the same API surface as bytecode and would double
            // every composable if they were on the compile classpath.
            val name = file.nameWithoutExtension
            if (name.endsWith("-sources")) return@forEach
            val json =
                if (file.extension == "aar") {
                    ZipFile(file).use { zip ->
                        val entry = zip.getEntry(classesJar) ?: return@use null
                        ComposeDump().dump(zip.getInputStream(entry).readBytes())
                    }
                } else {
                    ComposeDump().dump(file.readBytes())
                } ?: return@forEach
            if (json.isEmpty()) return@forEach
            File(target, "$name.json").writeText(json)
            artifacts++
            composables += json.split("  \"").size - 1
        }
        logger.lifecycle(
            "dumpComposeApi: $artifacts artifact(s), $composables composable(s)" +
                if (metadataFailures > 0) {
                    ", $metadataFailures class(es) degraded to descriptors"
                } else {
                    ""
                } + " -> $target",
        )
    }
}

/** One class's composable surface, as ASM reports it. */
private class ClassFacts {
    var name: String = ""
    var metadata: AnnotationFacts? = null
    val composables = mutableListOf<MethodFacts>()
}

/** One @Composable method. */
private class MethodFacts(
    val name: String,
    val descriptor: String,
)

/** The values of a single class-file annotation. */
private class AnnotationFacts {
    val values: MutableMap<String, Any?> = mutableMapOf()
}

/** Reads composables out of one jar's bytes. */
private class ComposeDump {
    /** Return `{ "fqcn": ["name(a: T, b: U)", ...] }`, or an empty string. */
    fun dump(bytes: ByteArray): String {
        val byClass = sortedMapOf<String, List<String>>()
        ZipInputStream(ByteArrayInputStream(bytes)).use { zip ->
            var entry = zip.nextEntry
            while (entry != null) {
                if (entry.name.endsWith(".class") && !entry.name.contains('$')) {
                    val facts = read(zip.readBytes())
                    if (facts != null && facts.composables.isNotEmpty()) {
                        byClass[facts.name.replace('/', '.')] = render(facts)
                    }
                }
                zip.closeEntry()
                entry = zip.nextEntry
            }
        }
        return byClass.entries.joinToString(",\n", "{\n", "\n}") { (fqcn, composables) ->
            composables.joinToString(",\n", "\"$fqcn\": [\n", "\n]") { "  \"$it\"" }
        }
    }

    /** Collect one class's name, its @Metadata and its @Composable methods. */
    private fun read(bytes: ByteArray): ClassFacts? {
        val facts = ClassFacts()
        org.objectweb.asm.ClassReader(bytes).accept(
            object : org.objectweb.asm.ClassVisitor(asm9) {
                override fun visit(
                    version: Int,
                    access: Int,
                    name: String,
                    signature: String?,
                    superName: String?,
                    interfaces: Array<out String>?,
                ) {
                    facts.name = name
                }

                override fun visitAnnotation(
                    descriptor: String,
                    visible: Boolean,
                ): org.objectweb.asm.AnnotationVisitor? {
                    if (descriptor != metadataDescriptor || !visible) return null
                    val annotation = AnnotationFacts()
                    facts.metadata = annotation
                    return Collector(annotation)
                }

                override fun visitMethod(
                    access: Int,
                    name: String,
                    descriptor: String,
                    signature: String?,
                    exceptions: Array<out String>?,
                ): org.objectweb.asm.MethodVisitor {
                    val method = MethodFacts(name, descriptor)
                    return object : org.objectweb.asm.MethodVisitor(asm9) {
                        // @Composable has BINARY retention, so it reaches the
                        // visitor with visible=false. Checking only for visible
                        // finds zero composables in the entire classpath, which
                        // looks exactly like a Compose library that declares
                        // nothing -- the failure this dump would otherwise ship
                        // silently, and did, once.
                        override fun visitAnnotation(
                            annotationDescriptor: String,
                            visibleAnnotation: Boolean,
                        ): org.objectweb.asm.AnnotationVisitor? {
                            if (annotationDescriptor == composableDescriptor) {
                                facts.composables.add(method)
                            }
                            return null
                        }
                    }
                }
            },
            org.objectweb.asm.ClassReader.SKIP_CODE or org.objectweb.asm.ClassReader.SKIP_DEBUG,
        )
        return facts
    }

    /**
     * Drop the Compose compiler's synthetic tail.
     *
     * Every @Composable is compiled to `(realParams..., Composer, Int, Int)`,
     * and that tail is not part of the signature a developer writes. Reporting
     * it would put a `Composer` parameter on every one of the 983 composables,
     * and a schema generated from that would model a parameter no call site can
     * supply.
     */
    private fun trimmed(parts: List<String>): List<String> {
        var end = parts.size
        while (end > 0 && isSynthetic(parts[end - 1])) end--
        return parts.subList(0, end)
    }

    private fun isSynthetic(part: String): Boolean =
        part.endsWith(": Composer") ||
            part.endsWith(": Int") ||
            part.endsWith(": int") ||
            part.startsWith("arg") && part.contains(": int")

    /** Render each composable as `name(a: T, b: U)`. */
    private fun render(facts: ClassFacts): List<String> {
        val kmClass = decodeMetadata(facts.metadata)
        return facts.composables
            .map { method ->
                // Kotlin mangles an internal inline function's JVM name by
                // appending a hash -- `Text` is really `Text--4IGK_g`, and so is
                // every one of its overloads. Matching the metadata by the mangled
                // name finds nothing, so every parameter falls back to arg0; and
                // reporting the mangled name makes five overloads of one function
                // look like five unrelated composables. The metadata holds the real
                // name, so prefer it and fall back to the JVM name.
                val plain = method.name.substringBefore('-')
                val types =
                    org.objectweb.asm.Type
                        .getArgumentTypes(method.descriptor)
                val firstJvm = types.firstOrNull()?.className?.substringAfterLast('.')
                // Matching metadata by name alone is wrong the moment a function is
                // overloaded: all four JVM `Text` methods share the name, so the
                // first metadata entry wins for every one of them and the two
                // String overloads are reported as AnnotatedString. The descriptor
                // distinguishes them, so match on the first argument's type too.
                val named =
                    kmClass?.functions?.filter { it.name == method.name || it.name == plain }
                val km =
                    named?.firstOrNull {
                        it.valueParameters
                            .firstOrNull()
                            ?.type
                            ?.render() == firstJvm
                    }
                        ?: named?.firstOrNull()
                val declared = km?.name ?: plain
                val parts =
                    types.mapIndexed { index, type ->
                        val declared = km?.valueParameters?.getOrNull(index)
                        val name = declared?.name ?: "arg$index"
                        // Metadata names the Kotlin-level parameters; the descriptor
                        // knows the JVM-level types. They disagree at exactly one
                        // point that matters here -- a Function0 content slot and a
                        // Function1 callback are different types, which is the whole
                        // reason to read bytecode instead of a published text dump.
                        val kotlin =
                            declared?.type?.render() ?: type.className.substringAfterLast('.')
                        "$name: $kotlin"
                    }
                "$declared(${trimmed(parts).joinToString(", ")})"
            }.sorted()
    }

    /**
     * Decode the @Metadata blob, or null when unusable.
     *
     * A file facade's functions live on its `KmPackage` and a class's on its
     * `KmClass`; both satisfy the declaration container the caller reads from.
     * A version this kotlinx-metadata cannot parse degrades to JVM descriptors
     * alone rather than failing the whole dump: names would be lost, arity and
     * types -- including the Function0/Function1 distinction -- would not.
     */
    private fun decodeMetadata(
        annotation: AnnotationFacts?,
    ): kotlinx.metadata.KmDeclarationContainer? {
        val values = annotation?.values ?: return null

        // d1 and d2 are *parallel* String arrays -- index i of one corresponds
        // to index i of the other -- and both are handed over whole. Collapsing
        // either to its first element makes the pair inconsistent, and the
        // reader throws InconsistentKotlinMetadataException for every class in
        // the jar. That is the difference between names and arg0.
        fun blob(key: String): Array<String> =
            when (val value = values[key]) {
                is Array<*> -> value.map { it?.toString().orEmpty() }.toTypedArray()
                is String -> arrayOf(value)
                else -> emptyArray()
            }
        val d1 = blob("d1")
        val d2 = blob("d2")
        // d2 is legitimately empty: Kotlin 1.9 introduced a compact metadata
        // form that packs everything into d1 and omits d2. Treating that as
        // "no metadata" costs every parameter name in every modern jar, which is
        // most of them -- and Compose is compiled by a recent compiler.
        if (d1.isEmpty()) return null

        fun ints(key: String): IntArray =
            when (val value = values[key]) {
                is IntArray -> value
                is Array<*> -> value.filterIsInstance<Number>().map { it.toInt() }.toIntArray()
                else -> intArrayOf(1, 0, 0)
            }
        // Kotlin spells the annotation's parameters out in full where the JVM
        // calls them k/mv/d1; the compiler resolves the Kotlin names, and naming
        // them the Java way fails at the call site rather than at the annotation.
        // d1/d2 are String[] on the class file and hold one element here -- the
        // reader splits them internally, so the blob is passed whole.
        val header =
            metadata(
                kind = values["k"] as? Int ?: 1,
                metadataVersion = ints("mv"),
                bytecodeVersion = ints("bv"),
                // Passed whole: the reader splits them internally.
                data1 = d1,
                data2 = d2,
                extraString = values["xs"] as? String ?: "",
                packageName = values["pn"] as? String ?: "",
                extraInt = values["xi"] as? Int ?: 0,
            )
        // readLenient tolerates a *newer* metadata version; it still throws on
        // data it cannot parse at all, which happens for synthetic and
        // pre-release shapes inside an otherwise ordinary jar. One such class
        // must not fail the dump: degrade to JVM descriptors, which keep arity
        // and types -- including the Function0/Function1 distinction that the
        // whole approach exists for -- and lose only the parameter names.
        return try {
            // ButtonKt is a *file facade*, and 0.9 models that as its own case
            // rather than as a Class. Every top-level composable lives in one, so
            // matching only Class finds metadata for classes and nothing for the
            // functions anyone actually wants to mirror.
            when (
                val parsed =
                    kotlinx.metadata.jvm.KotlinClassMetadata
                        .readLenient(header)
            ) {
                is kotlinx.metadata.jvm.KotlinClassMetadata.Class -> parsed.kmClass
                is kotlinx.metadata.jvm.KotlinClassMetadata.FileFacade -> parsed.kmPackage
                else -> null
            }
        } catch (failure: Throwable) {
            metadataFailures++
            null
        }
    }
}

/**
 * Build a `kotlin.Metadata` carrying values read at runtime.
 *
 * Three ways to do this, all awkward, and the reason is worth recording:
 * `Metadata(...)` is an annotation, so Kotlin demands compile-time constants
 * for its arguments; implementing the interface hits Kotlin's own view of it,
 * where `kind` is a final val; and naming the properties the way the JVM does
 * (`k`, `mv`, `d1`) is not how Kotlin sees them either.
 *
 * A dynamic proxy sidesteps all of it. The interface is a runtime interface, so
 * the answer is keyed by method name and never has to agree with either naming.
 */
private fun metadata(
    kind: Int,
    metadataVersion: IntArray,
    bytecodeVersion: IntArray,
    data1: Array<String>,
    data2: Array<String>,
    extraString: String,
    packageName: String,
    extraInt: Int,
): kotlin.Metadata {
    val answers =
        mapOf(
            "k" to kind,
            "mv" to metadataVersion,
            "bv" to bytecodeVersion,
            "d1" to data1,
            "d2" to data2,
            "xs" to extraString,
            "pn" to packageName,
            "xi" to extraInt,
        )
    val proxy =
        java.lang.reflect.Proxy.newProxyInstance(
            kotlin.Metadata::class.java.classLoader,
            arrayOf(kotlin.Metadata::class.java),
        ) { _, method, _ -> answers[method.name] }
    return proxy as kotlin.Metadata
}

/**
 * Reads an annotation's `name = value` pairs.
 *
 * Arrays matter and returning null for them is the trap: d1, d2 and bv are all
 * arrays, so dropping them leaves a `kotlin.Metadata` with a kind and nothing
 * else. The reader then fails, `decodeMetadata` returns null, and every
 * parameter name falls back to `arg0` -- a dump that looks complete and has
 * lost the half that makes it useful.
 */
private class Collector(
    private val into: AnnotationFacts,
) : org.objectweb.asm.AnnotationVisitor(asm9) {
    private var pending: String? = null
    private var elements: MutableList<Any?>? = null

    override fun visit(
        name: String?,
        value: Any?,
    ) {
        if (name == null) {
            elements?.add(value)
            return
        }
        into.values[name] = value
    }

    override fun visitArray(name: String): org.objectweb.asm.AnnotationVisitor {
        pending = name
        elements = mutableListOf()
        return object : org.objectweb.asm.AnnotationVisitor(asm9) {
            override fun visit(
                ignored: String?,
                value: Any?,
            ) {
                elements?.add(value)
            }

            override fun visitEnum(
                ignored: String,
                descriptor: String,
                value: String?,
            ) {
                elements?.add(value)
            }

            override fun visitEnd() {
                val collected = elements
                if (pending != null && collected != null) {
                    // A String[] stays an array; an int[] stays an array. Which
                    // one matters: Metadata declares d1/d2 as String[].
                    into.values[pending!!] =
                        if (collected.all { it is String }) {
                            collected.toTypedArray()
                        } else {
                            collected.filterIsInstance<Number>().map { it.toInt() }.toIntArray()
                        }
                }
                pending = null
                elements = null
            }
        }
    }

    override fun visitAnnotation(
        name: String,
        descriptor: String,
    ): org.objectweb.asm.AnnotationVisitor? = null

    override fun visitEnum(
        name: String,
        descriptor: String,
        value: String?,
    ) {
        if (name != null) into.values[name] = value
    }
}

/**
 * Render a Kotlin type the way the schema's wire vocabulary sees it.
 *
 * `KmClassifier` is a sealed hierarchy in kotlinx-metadata 0.9, so there is no
 * `.name` on the base: a class and a type alias have to be matched apart.
 */
private fun kotlinx.metadata.KmType.render(): String {
    val classifier =
        when (val node = classifier) {
            is kotlinx.metadata.KmClassifier.Class -> node.name
            is kotlinx.metadata.KmClassifier.TypeAlias -> node.name
            // 0.9 carries only a type parameter's id, not its bound, so this
            // renders as the erasure rather than as a guess.
            is kotlinx.metadata.KmClassifier.TypeParameter -> "Any"
        }
    val generic = arguments.firstOrNull()?.type?.render()
    val simple = classifier.substringAfterLast('.').substringAfterLast('/')
    return if (generic == null) simple else "$simple<$generic>"
}
