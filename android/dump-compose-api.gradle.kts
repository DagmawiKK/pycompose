import groovy.json.JsonOutput
import kotlinx.metadata.ClassKind
import kotlinx.metadata.ExperimentalContextReceivers
import kotlinx.metadata.KmAnnotationArgument
import kotlinx.metadata.KmClassifier
import kotlinx.metadata.KmDeclarationContainer
import kotlinx.metadata.KmType
import kotlinx.metadata.KmTypeParameter
import kotlinx.metadata.KmValueParameter
import kotlinx.metadata.Visibility
import kotlinx.metadata.declaresDefaultValue
import kotlinx.metadata.isNullable
import kotlinx.metadata.isSuspend
import kotlinx.metadata.jvm.JvmMethodSignature
import kotlinx.metadata.jvm.KotlinClassMetadata
import kotlinx.metadata.jvm.annotations
import kotlinx.metadata.jvm.fieldSignature
import kotlinx.metadata.jvm.getterSignature
import kotlinx.metadata.jvm.setterSignature
import kotlinx.metadata.jvm.signature
import kotlinx.metadata.jvm.syntheticMethodForAnnotations
import kotlinx.metadata.kind
import kotlinx.metadata.modality
import kotlinx.metadata.visibility
import org.gradle.api.artifacts.component.ModuleComponentSelector
import org.objectweb.asm.AnnotationVisitor
import org.objectweb.asm.ClassReader
import org.objectweb.asm.ClassVisitor
import org.objectweb.asm.FieldVisitor
import org.objectweb.asm.MethodVisitor
import org.objectweb.asm.Opcodes
import java.io.ByteArrayInputStream
import java.security.MessageDigest
import java.util.zip.ZipFile
import java.util.zip.ZipInputStream

// Development tooling only. Read the actual Android variant, never a separately
// resolved desktop/stub artifact or AndroidX main. The runtime uses no metadata.
buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath("org.ow2.asm:asm:9.7.1")
        classpath("org.jetbrains.kotlinx:kotlinx-metadata-jvm:0.9.0")
        classpath("org.jetbrains.kotlin:kotlin-stdlib:1.9.23")
    }
}

val composeAnnotation = "androidx/compose/runtime/Composable"
val apiFormatVersion = 1
val apiRenderer = project(":renderer")

tasks.register("dumpComposeApi") {
    group = "build"
    description = "Extract a lossless, version-proven Compose API inventory."
    val rendererClasspath = apiRenderer.configurations.getByName("debugCompileClasspath")
    val output = layout.buildDirectory.file("compose-api/inventory.json")
    inputs.files(rendererClasspath)
    inputs.file("dump-compose-api.gradle.kts")
    inputs.file("gradle/libs.versions.toml")
    val sourceInputs =
        project.fileTree(".") {
            include(
                "*.gradle.kts",
                "*/build.gradle.kts",
                "gradle/libs.versions.toml",
                "gradle.properties",
            )
        }
    inputs.files(sourceInputs)
    outputs.file(output)
    doLast {
        val artifacts = mutableListOf<Map<String, Any?>>()
        val declarations = mutableListOf<Map<String, Any?>>()
        val classFacts = mutableListOf<Map<String, Any?>>()
        val diagnostics = mutableListOf<Map<String, Any?>>()
        val variants =
            rendererClasspath.incoming.artifacts.artifacts
                .associateBy { it.file.canonicalPath }
        rendererClasspath.resolvedConfiguration.resolvedArtifacts
            .filter {
                it.moduleVersion.id.group
                    .startsWith("androidx.compose")
            }.sortedBy { it.moduleVersion.id.toString() }
            .forEach { artifact ->
                val coordinate = artifact.moduleVersion.id.toString()
                val file = artifact.file
                val bytes = file.readBytes()
                val attributes = checkNotNull(variants[file.canonicalPath]).variant.attributes
                val variantAttributes =
                    attributes.keySet().associate {
                        it.name to attributes.getAttribute(it).toString()
                    }
                artifacts.add(
                    mapOf(
                        "coordinate" to coordinate,
                        "sha256" to sha256(bytes),
                        "variant" to variantAttributes["org.jetbrains.kotlin.platform.type"],
                        "attributes" to variantAttributes.toSortedMap(),
                        "file" to file.name,
                    ),
                )
                val classes =
                    if (file.extension == "aar") {
                        ZipFile(file).use { zip ->
                            val entry =
                                checkNotNull(zip.getEntry("classes.jar")) {
                                    "$coordinate lacks classes.jar"
                                }
                            zip.getInputStream(entry).readBytes()
                        }
                    } else {
                        bytes
                    }
                val extracted = ApiExtractor(coordinate, diagnostics).extract(classes)
                declarations.addAll(extracted.declarations)
                classFacts.addAll(extracted.classes)
            }
        val bomComponent =
            rendererClasspath.incoming.resolutionResult.allComponents
                .single {
                    it.moduleVersion?.let { m ->
                        m.group == "androidx.compose" && m.name == "compose-bom"
                    } == true
                }
        val bom = checkNotNull(bomComponent.moduleVersion).version
        val bomConstraints =
            bomComponent.dependencies
                .mapNotNull {
                    (it.requested as? ModuleComponentSelector)?.let { m ->
                        "${m.group}:${m.module}" to m.version
                    }
                }.toMap()
                .toSortedMap()
        val overrides =
            artifacts.mapNotNull {
                val coordinate = it["coordinate"].toString()
                val module = coordinate.substringBeforeLast(':')
                val expected = bomConstraints[module]
                if (expected != null && expected != coordinate.substringAfterLast(':')) {
                    "$module expected $expected, resolved ${coordinate.substringAfterLast(':')}"
                } else {
                    null
                }
            }
        val compiler =
            project.extensions
                .getByType<VersionCatalogsExtension>()
                .named("libs")
                .findVersion("kotlin")
                .get()
                .requiredVersion
        val document =
            mapOf(
                "formatVersion" to apiFormatVersion,
                "provenance" to
                    mapOf(
                        "configuration" to ":renderer:debugCompileClasspath",
                        "bom" to bom,
                        "compiler" to compiler,
                        "bomConstraints" to bomConstraints,
                        "overrides" to overrides,
                        "sourceHashes" to
                            sourceInputs.files
                                .sortedBy {
                                    it.relativeTo(project.projectDir).invariantSeparatorsPath
                                }.associate {
                                    it.relativeTo(project.projectDir).invariantSeparatorsPath to
                                        sha256(it.readBytes())
                                },
                    ),
                "artifacts" to artifacts,
                "declarations" to
                    declarations.sortedBy {
                        "${it["owner"]}:${it["name"]}:${it["jvm"]}"
                    },
                "classes" to
                    classFacts.sortedBy {
                        "${it["owner"]}:${it["classKind"]}"
                    },
                "diagnostics" to diagnostics.sortedBy { it["message"].toString() },
                "bytecodeAudit" to
                    mapOf(
                        "unmatchedTargetMethods" to
                            diagnostics.filter {
                                it["target"] == true && it["unmatchedBytecode"] == true
                            },
                    ),
            )
        val target = output.get().asFile
        target.parentFile.mkdirs()
        val temporary = File(target.parentFile, "inventory.json.pending")
        temporary.writeText(JsonOutput.toJson(document) + "\n")
        java.nio.file.Files.move(
            temporary.toPath(),
            target.toPath(),
            java.nio.file.StandardCopyOption.REPLACE_EXISTING,
            java.nio.file.StandardCopyOption.ATOMIC_MOVE,
        )
        val ui = declarations.count { it["disposition"] == "ui" }
        logger.lifecycle(
            "dumpComposeApi: $ui public M3 overloads, ${declarations.size} declarations, " +
                "${diagnostics.size} extraction errors -> $target",
        )
        val targetErrors = diagnostics.filter { it["target"] == true }
        check(targetErrors.isEmpty()) {
            targetErrors.take(20).joinToString("\n", "Compose extraction failed:\n")
        }
        check(overrides.isEmpty()) { "Compose BOM overrides: $overrides" }
        check(ui > 0) { "The resolved classpath contains no public Material 3 UI." }
    }
}

private fun sha256(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

private class ClassApi {
    var name = ""
    var sourceFile: String? = null
    var access = 0
    var metadata: MutableMap<String, Any?>? = null
    val annotations = sortedMapOf<String, MutableMap<String, Any?>>()
    val methods = mutableListOf<MethodApi>()
    val fields = mutableMapOf<Pair<String, String>, Pair<Int, Any?>>()
}

private class MethodApi(
    val name: String,
    val descriptor: String,
    val access: Int,
) {
    val annotations = sortedMapOf<String, MutableMap<String, Any?>>()
}

/** Every annotation owns its array visitors; nested arrays never share state. */
private fun annotationValues(into: MutableMap<String, Any?>): AnnotationVisitor =
    object : AnnotationVisitor(Opcodes.ASM9) {
        override fun visit(
            name: String,
            value: Any?,
        ) {
            into[name] = value
        }

        override fun visitEnum(
            name: String,
            descriptor: String,
            value: String,
        ) {
            into[name] = value
        }

        override fun visitArray(name: String): AnnotationVisitor {
            val items = mutableListOf<Any?>()
            into[name] = items
            return object : AnnotationVisitor(Opcodes.ASM9) {
                override fun visit(
                    name: String?,
                    value: Any?,
                ) {
                    items.add(value)
                }

                override fun visitEnum(
                    name: String?,
                    descriptor: String,
                    value: String,
                ) {
                    items.add(value)
                }

                override fun visitAnnotation(
                    name: String?,
                    descriptor: String,
                ): AnnotationVisitor {
                    val values = mutableMapOf<String, Any?>()
                    items.add(mapOf("annotation" to descriptor, "values" to values))
                    return annotationValues(values)
                }

                override fun visitArray(name: String?): AnnotationVisitor {
                    val values = mutableMapOf<String, Any?>()
                    items.add(values)
                    return annotationValues(values).visitArray("items")
                }
            }
        }

        override fun visitAnnotation(
            name: String,
            descriptor: String,
        ): AnnotationVisitor {
            val values = mutableMapOf<String, Any?>()
            into[name] = mapOf("annotation" to descriptor, "values" to values)
            return annotationValues(values)
        }
    }

private fun readClass(bytes: ByteArray): ClassApi {
    val facts = ClassApi()
    ClassReader(bytes).accept(
        object : ClassVisitor(Opcodes.ASM9) {
            override fun visit(
                version: Int,
                access: Int,
                name: String,
                signature: String?,
                superName: String?,
                interfaces: Array<out String>?,
            ) {
                facts.name = name
                facts.access = access
            }

            override fun visitSource(
                source: String?,
                debug: String?,
            ) {
                facts.sourceFile = source
            }

            override fun visitAnnotation(
                descriptor: String,
                visible: Boolean,
            ): AnnotationVisitor {
                val values = mutableMapOf<String, Any?>()
                val name = descriptor.removePrefix("L").removeSuffix(";")
                facts.annotations[name] = values
                if (name == "kotlin/Metadata") facts.metadata = values
                return annotationValues(values)
            }

            override fun visitMethod(
                access: Int,
                name: String,
                descriptor: String,
                signature: String?,
                exceptions: Array<out String>?,
            ): MethodVisitor {
                val method = MethodApi(name, descriptor, access)
                facts.methods.add(method)
                return object : MethodVisitor(Opcodes.ASM9) {
                    override fun visitAnnotation(
                        descriptor: String,
                        visible: Boolean,
                    ): AnnotationVisitor {
                        val values = mutableMapOf<String, Any?>()
                        method.annotations[descriptor.removePrefix("L").removeSuffix(";")] = values
                        return annotationValues(values)
                    }
                }
            }

            override fun visitField(
                access: Int,
                name: String,
                descriptor: String,
                signature: String?,
                value: Any?,
            ): FieldVisitor? {
                facts.fields[name to descriptor] = access to value
                return null
            }
        },
        ClassReader.SKIP_CODE or ClassReader.SKIP_FRAMES,
    )
    return facts
}

private fun decode(facts: ClassApi): KotlinClassMetadata? {
    val values = facts.metadata ?: return null

    fun strings(key: String): Array<String> =
        (values[key] as? List<*>)?.map { it as String }?.toTypedArray() ?: emptyArray()

    fun ints(key: String): IntArray = values[key] as? IntArray ?: intArrayOf()
    return KotlinClassMetadata.readLenient(
        kotlinx.metadata.jvm.Metadata(
            kind = values["k"] as? Int ?: 1,
            metadataVersion = ints("mv"),
            data1 = strings("d1"),
            data2 = strings("d2"),
            extraString = values["xs"] as? String ?: "",
            packageName = values["pn"] as? String ?: "",
            extraInt = values["xi"] as? Int ?: 0,
        ),
    )
}

private fun KmType.document(): Map<String, Any?> =
    mapOf(
        "classifier" to
            when (val node = classifier) {
                is KmClassifier.Class -> node.name
                is KmClassifier.TypeAlias -> node.name
                is KmClassifier.TypeParameter -> "#${node.id}"
            },
        "nullable" to isNullable,
        "suspend" to isSuspend,
        "annotations" to annotations.map { it.className }.sorted(),
        "annotationValues" to
            annotations.associate { a ->
                a.className to a.arguments.mapValues { it.value.document() }
            },
        "arguments" to
            arguments.map {
                mapOf("variance" to it.variance?.name, "type" to it.type?.document())
            },
        "abbreviatedType" to abbreviatedType?.document(),
        "outerType" to outerType?.document(),
        "flexibleUpperBound" to flexibleTypeUpperBound?.type?.document(),
    )

private fun KmAnnotationArgument.document(): Any? =
    when (this) {
        is KmAnnotationArgument.LiteralValue<*> -> value.toString()
        is KmAnnotationArgument.ArrayValue -> elements.map { it.document() }
        is KmAnnotationArgument.AnnotationValue ->
            mapOf(
                "annotation" to annotation.className,
                "values" to annotation.arguments.mapValues { it.value.document() },
            )
        is KmAnnotationArgument.EnumValue ->
            mapOf(
                "class" to enumClassName,
                "entry" to enumEntryName,
            )
        is KmAnnotationArgument.KClassValue -> mapOf("class" to className)
        is KmAnnotationArgument.ArrayKClassValue ->
            mapOf(
                "class" to className,
                "arrayDimensions" to arrayDimensionCount,
            )
    }

private class ApiExtractor(
    private val coordinate: String,
    private val diagnostics: MutableList<Map<String, Any?>>,
) {
    /** One artifact's public API plus the class facts its hierarchy needs. */
    class Extracted(
        val declarations: List<Map<String, Any?>>,
        val classes: List<Map<String, Any?>>,
    )

    @OptIn(ExperimentalContextReceivers::class)
    fun extract(bytes: ByteArray): Extracted {
        val classes = sortedMapOf<String, ClassApi>()
        ZipInputStream(ByteArrayInputStream(bytes)).use { zip ->
            var entry = zip.nextEntry
            while (entry != null) {
                if (entry.name.endsWith(".class")) {
                    val facts = readClass(zip.readBytes())
                    classes[facts.name] = facts
                }
                zip.closeEntry()
                entry = zip.nextEntry
            }
        }
        val metadata = classes.mapValues { (_, facts) -> decode(facts) }
        val declarations = mutableListOf<Map<String, Any?>>()
        for ((owner, facts) in classes) {
            val parsed = metadata[owner]
            val container: KmDeclarationContainer =
                when (parsed) {
                    is KotlinClassMetadata.Class -> parsed.kmClass
                    is KotlinClassMetadata.FileFacade -> parsed.kmPackage
                    is KotlinClassMetadata.MultiFileClassPart -> parsed.kmPackage
                    // Multifile facades delegate to their parts; synthetic lambda
                    // classes are implementations, not additional public APIs.
                    else -> continue
                }
            val enclosing = enclosingChain(owner)
            val classVisibility = visibilityOf(enclosing, metadata)
            val classAnnotations = annotationsOf(enclosing, classes)
            val dispatchReceiver =
                if (parsed is KotlinClassMetadata.Class) classType(owner).document() else null
            for (function in container.functions) {
                val signature = function.signature
                val method = facts.method(signature)
                val annotations =
                    (classAnnotations + method?.annotations.orEmpty())
                        .filterKeys { it != "kotlin/Metadata" }
                val composable = annotations.containsKey(composeAnnotation)
                val eligibility = exclusion(function.visibility, classVisibility, annotations)
                val m3 = owner.startsWith("androidx/compose/material3/")
                val reason =
                    when {
                        eligibility != null -> eligibility
                        method == null -> "metadata JVM signature has no bytecode method"
                        method.access and (Opcodes.ACC_SYNTHETIC or Opcodes.ACC_BRIDGE) != 0 ->
                            "synthetic or bridge method"
                        method.access and Opcodes.ACC_PUBLIC == 0 -> "non-public JVM method"
                        else -> null
                    }
                if (eligibility == null && method == null) {
                    diagnostics.add(
                        mapOf(
                            "target" to m3,
                            "message" to
                                "$coordinate $owner.${function.name}: unmatched $signature",
                        ),
                    )
                }
                val returnsUnit =
                    (function.returnType.classifier as? KmClassifier.Class)?.name == "kotlin/Unit"
                val contextProvider = function.name in setOf("MaterialTheme", "ProvideTextStyle")
                declarations.add(
                    mapOf(
                        "artifact" to coordinate,
                        "owner" to owner.replace('/', '.'),
                        "package" to owner.substringBeforeLast('/').replace('/', '.'),
                        "name" to function.name,
                        "declarationKind" to "function",
                        "suspend" to function.isSuspend,
                        "visibility" to function.visibility.name,
                        "classVisibility" to classVisibility.name,
                        "jvm" to facts.jvm(signature),
                        "disposition" to
                            when {
                                eligibility == null && method == null -> "error"
                                reason != null -> "excluded"
                                m3 && composable && returnsUnit && !contextProvider -> "ui"
                                else -> "support"
                            },
                        "category" to
                            when {
                                reason != null -> "excluded"
                                !m3 -> "foundation-ui-helper"
                                contextProvider -> "composition-provider"
                                composable && !returnsUnit -> "composable-factory"
                                else -> "material3"
                            },
                        "reason" to reason,
                        "composable" to composable,
                        "annotations" to annotations,
                        "receiver" to function.receiverParameterType?.document(),
                        "dispatchReceiver" to dispatchReceiver,
                        "contextReceivers" to function.contextReceiverTypes.map { it.document() },
                        "returnType" to function.returnType.document(),
                        "typeParameters" to function.typeParameters.map { it.document() },
                        "parameters" to function.valueParameters.map { it.document() },
                    ),
                )
            }
            for (property in container.properties) {
                fun accessor(
                    signature: JvmMethodSignature?,
                    visibility: Visibility?,
                ): Map<String, Any?>? =
                    signature?.let {
                        val method = facts.method(it)
                        val annotations = classAnnotations + method?.annotations.orEmpty()
                        val reason =
                            when {
                                visibility == null -> "missing accessor visibility"
                                exclusion(visibility, classVisibility, annotations) != null ->
                                    exclusion(visibility, classVisibility, annotations)
                                method == null -> "unmatched accessor"
                                method.access and Opcodes.ACC_PUBLIC == 0 ->
                                    "non-public JVM accessor"
                                else -> null
                            }
                        facts.jvm(it) +
                            mapOf(
                                "visibility" to visibility?.name,
                                "access" to method?.access,
                                "callable" to (reason == null),
                                "reason" to reason,
                            )
                    }
                val getter = accessor(property.getterSignature, property.getter.visibility)
                val setter = accessor(property.setterSignature, property.setter?.visibility)
                // Kotlin companion @JvmField/const properties are physically
                // emitted on the enclosing class, not on the Companion class.
                val fieldOwner =
                    if (parsed is KotlinClassMetadata.Class &&
                        parsed.kmClass.kind == ClassKind.COMPANION_OBJECT
                    ) {
                        classes[owner.substringBeforeLast('$')]
                    } else {
                        facts
                    }
                val field =
                    property.fieldSignature?.let {
                        facts.fields[it.name to it.descriptor]
                            ?: fieldOwner?.fields?.get(it.name to it.descriptor)
                    }
                val signatures =
                    listOfNotNull(
                        property.getterSignature,
                        property.setterSignature,
                        property.syntheticMethodForAnnotations,
                    )
                val methods = signatures.mapNotNull { facts.method(it) }
                val annotations =
                    (
                        classAnnotations +
                            methods
                                .flatMap {
                                    it.annotations.entries
                                }.associate { it.toPair() }
                    ).filterKeys { it != "kotlin/Metadata" }
                val eligibility = exclusion(property.visibility, classVisibility, annotations)
                val matched = getter?.get("matched") == true || field != null
                val unreadAccessor =
                    listOfNotNull(getter, setter).any {
                        it["visibility"] == "PUBLIC" && it["matched"] != true
                    }
                val reason =
                    when {
                        eligibility != null -> eligibility
                        !matched || unreadAccessor -> "unmatched property accessor/field"
                        else -> null
                    }
                if (eligibility == null && reason == "unmatched property accessor/field") {
                    diagnostics.add(
                        mapOf(
                            "target" to owner.startsWith("androidx/compose/material3/"),
                            "message" to "$coordinate $owner.${property.name}: $reason",
                        ),
                    )
                }
                declarations.add(
                    mapOf(
                        "artifact" to coordinate,
                        "owner" to owner.replace('/', '.'),
                        "package" to owner.substringBeforeLast('/').replace('/', '.'),
                        "name" to property.name,
                        "declarationKind" to "property",
                        "visibility" to property.visibility.name,
                        "classVisibility" to classVisibility.name,
                        "jvm" to (
                            getter ?: mapOf(
                                "name" to property.fieldSignature?.name,
                                "descriptor" to property.fieldSignature?.descriptor,
                                "matched" to matched,
                            )
                        ),
                        "accessors" to mapOf("getter" to getter, "setter" to setter),
                        "constant" to field?.second,
                        "disposition" to
                            when {
                                reason == "unmatched property accessor/field" -> "error"
                                reason != null -> "excluded"
                                else -> "support"
                            },
                        "reason" to reason,
                        "composable" to annotations.containsKey(composeAnnotation),
                        "annotations" to annotations,
                        "receiver" to property.receiverParameterType?.document(),
                        "dispatchReceiver" to dispatchReceiver,
                        "contextReceivers" to property.contextReceiverTypes.map { it.document() },
                        "returnType" to property.returnType.document(),
                        "parameters" to emptyList<Any>(),
                        "typeParameters" to property.typeParameters.map { it.document() },
                    ),
                )
            }
            if (parsed is KotlinClassMetadata.Class) {
                for (constructor in parsed.kmClass.constructors) {
                    val signature = constructor.signature
                    val method = facts.method(signature)
                    val annotations =
                        (classAnnotations + method?.annotations.orEmpty())
                            .filterKeys { it != "kotlin/Metadata" }
                    val eligibility =
                        exclusion(
                            constructor.visibility,
                            classVisibility,
                            annotations,
                        )
                    val reason =
                        when {
                            eligibility != null -> eligibility
                            parsed.kmClass.kind == ClassKind.ANNOTATION_CLASS ->
                                "annotation constructors are not JVM callables"
                            method == null -> "unmatched constructor"
                            else -> null
                        }
                    if (reason == "unmatched constructor") {
                        diagnostics.add(
                            mapOf(
                                "target" to owner.startsWith("androidx/compose/material3/"),
                                "message" to "$coordinate $owner: $reason",
                            ),
                        )
                    }
                    declarations.add(
                        mapOf(
                            "artifact" to coordinate,
                            "owner" to owner.replace('/', '.'),
                            "package" to owner.substringBeforeLast('/').replace('/', '.'),
                            "name" to "<init>",
                            "declarationKind" to "constructor",
                            "visibility" to constructor.visibility.name,
                            "classVisibility" to classVisibility.name,
                            "jvm" to facts.jvm(signature),
                            "disposition" to
                                when {
                                    reason == "unmatched constructor" -> "error"
                                    reason != null -> "excluded"
                                    else -> "support"
                                },
                            "reason" to reason,
                            "composable" to false,
                            "annotations" to annotations,
                            "receiver" to null,
                            "dispatchReceiver" to null,
                            "contextReceivers" to emptyList<Any>(),
                            "returnType" to classType(owner).document(),
                            "typeParameters" to emptyList<Any>(),
                            "parameters" to constructor.valueParameters.map { it.document() },
                        ),
                    )
                }
            }
            if (owner.startsWith("androidx/compose/material3/") &&
                classVisibility == Visibility.PUBLIC
            ) {
                val metadataSignatures =
                    container.functions.mapNotNull { it.signature } +
                        container.properties.flatMap {
                            listOfNotNull(
                                it.getterSignature,
                                it.setterSignature,
                                it.syntheticMethodForAnnotations,
                            )
                        }
                facts.methods
                    .filter { m ->
                        composeAnnotation in m.annotations &&
                            m.access and Opcodes.ACC_PUBLIC != 0 &&
                            m.access and (Opcodes.ACC_SYNTHETIC or Opcodes.ACC_BRIDGE) == 0 &&
                            metadataSignatures.none {
                                it.name == m.name && it.descriptor == m.descriptor
                            }
                    }.forEach { m ->
                        diagnostics.add(
                            mapOf(
                                "target" to true,
                                "unmatchedBytecode" to true,
                                "message" to
                                    "$coordinate $owner.${m.name}${m.descriptor}: " +
                                    "annotated bytecode has no metadata declaration",
                            ),
                        )
                    }
            }
        }
        // Declaration-free classes carry no members, but the wire still needs
        // their hierarchy: Alignment.Vertical is only a subtype of Alignment
        // because the class itself says so.
        val classEvidence = mutableListOf<Map<String, Any?>>()
        for ((owner, facts) in classes) {
            val kmClass =
                (metadata[owner] as? KotlinClassMetadata.Class)?.kmClass ?: continue
            val chain = enclosingChain(owner)
            classEvidence.add(
                mapOf(
                    "artifact" to coordinate,
                    "owner" to owner.replace('/', '.'),
                    // Metadata spelling: packages and nesting separated by '.',
                    // which is exactly how a signature names the type.
                    "classifier" to kmClass.name.replace('/', '.'),
                    "package" to owner.substringBeforeLast('/').replace('/', '.'),
                    "sourceFile" to facts.sourceFile,
                    "classKind" to kmClass.kind.name,
                    "classModality" to kmClass.modality?.name,
                    "classVisibility" to visibilityOf(chain, metadata).name,
                    "classSupertypes" to kmClass.supertypes.map { it.document() },
                    "enumEntries" to kmClass.enumEntries,
                    "annotations" to annotationsOf(chain, classes),
                ),
            )
        }
        return Extracted(
            declarations.map { declaration ->
                val owner = declaration["owner"].toString().replace('.', '/')
                val kmClass = (metadata[owner] as? KotlinClassMetadata.Class)?.kmClass
                declaration +
                    mapOf(
                        "sourceFile" to classes[owner]?.sourceFile,
                        "classKind" to kmClass?.kind?.name,
                        // Modality decides whether a constructor is callable at
                        // all: an abstract class exposes one that can never be
                        // invoked.
                        "classModality" to kmClass?.modality?.name,
                        "enumEntries" to kmClass?.enumEntries.orEmpty(),
                        "enclosingTypeParameters" to
                            kmClass?.typeParameters.orEmpty().map {
                                it.document()
                            },
                        "classSupertypes" to kmClass?.supertypes.orEmpty().map { it.document() },
                    )
            },
            classEvidence,
        )
    }

    /** The class itself followed by every enclosing class or file facade. */
    private fun enclosingChain(owner: String): List<String> =
        generateSequence(owner) {
            if ('$' in it) it.substringBeforeLast('$') else null
        }.toList()

    /** The most restrictive visibility anywhere in the enclosing chain. */
    private fun visibilityOf(
        chain: List<String>,
        metadata: Map<String, KotlinClassMetadata?>,
    ): Visibility =
        chain
            .mapNotNull {
                (metadata[it] as? KotlinClassMetadata.Class)?.kmClass?.visibility
            }.firstOrNull { it != Visibility.PUBLIC } ?: Visibility.PUBLIC

    /** Annotations declared anywhere in the enclosing chain, minus stdlib noise. */
    private fun annotationsOf(
        chain: List<String>,
        classes: Map<String, ClassApi>,
    ): Map<String, MutableMap<String, Any?>> =
        chain
            .flatMap { classes[it]?.annotations.orEmpty().entries }
            .associate { it.toPair() }
            .filterKeys { it != "kotlin/Metadata" }
}

private fun classType(name: String): KmType =
    KmType().apply { classifier = KmClassifier.Class(name) }

private fun ClassApi.method(signature: JvmMethodSignature?): MethodApi? =
    methods.singleOrNull { it.name == signature?.name && it.descriptor == signature.descriptor }

private fun ClassApi.jvm(signature: JvmMethodSignature?): Map<String, Any?> =
    mapOf(
        "name" to signature?.name,
        "descriptor" to signature?.descriptor,
        "matched" to (method(signature) != null),
    )

private fun KmValueParameter.document(): Map<String, Any?> =
    mapOf(
        "name" to name,
        "type" to type.document(),
        "hasDefault" to declaresDefaultValue,
        "varargType" to varargElementType?.document(),
    )

private fun KmTypeParameter.document(): Map<String, Any?> =
    mapOf(
        "id" to id,
        "name" to name,
        "variance" to variance.name,
        "bounds" to upperBounds.map { it.document() },
    )

private fun exclusion(
    visibility: Visibility,
    classVisibility: Visibility,
    annotations: Map<String, Map<String, Any?>>,
): String? =
    when {
        visibility != Visibility.PUBLIC || classVisibility != Visibility.PUBLIC ->
            "non-public Kotlin declaration"
        "androidx/annotation/RestrictTo" in annotations -> "restricted API"
        annotations["kotlin/Deprecated"]?.get(
            "level",
        ) == "HIDDEN" -> "hidden compatibility declaration"
        else -> null
    }
