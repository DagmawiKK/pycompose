import kotlinx.metadata.ExperimentalContextReceivers
import kotlinx.metadata.KmClassifier
import kotlinx.metadata.KmFunction
import kotlinx.metadata.KmType
import kotlinx.metadata.isNullable
import kotlinx.metadata.isSuspend
import kotlinx.metadata.jvm.JvmMethodSignature
import kotlinx.metadata.jvm.KotlinClassMetadata
import kotlinx.metadata.jvm.annotations
import kotlinx.metadata.jvm.signature
import kotlinx.metadata.kind
import org.objectweb.asm.AnnotationVisitor
import org.objectweb.asm.ClassReader
import org.objectweb.asm.ClassVisitor
import org.objectweb.asm.FieldVisitor
import org.objectweb.asm.MethodVisitor
import org.objectweb.asm.Opcodes
import java.io.ByteArrayInputStream
import java.util.zip.ZipInputStream

internal class ClassApi {
    var name = ""
    var sourceFile: String? = null
    var access = 0
    var metadata: MutableMap<String, Any?>? = null
    val annotations = sortedMapOf<String, MutableMap<String, Any?>>()
    val methods = mutableListOf<MethodApi>()
    val fields = mutableMapOf<Pair<String, String>, Pair<Int, Any?>>()

    fun method(signature: JvmMethodSignature?): MethodApi? =
        methods.singleOrNull { it.name == signature?.name && it.descriptor == signature.descriptor }

    fun jvm(signature: JvmMethodSignature?): Map<String, Any?> = mapOf(
        "name" to signature?.name,
        "descriptor" to signature?.descriptor,
        "matched" to (method(signature) != null),
    )
}

internal class MethodApi(val name: String, val descriptor: String, val access: Int) {
    val annotations = sortedMapOf<String, MutableMap<String, Any?>>()
}

/** Every annotation owns its array visitors; nested arrays never share state. */
internal fun annotationValue(value: Any?): Any? =
    if (value is org.objectweb.asm.Type) mapOf("classDescriptor" to value.descriptor) else value

internal fun annotationValues(into: MutableMap<String, Any?>): AnnotationVisitor =
    object : AnnotationVisitor(Opcodes.ASM9) {
        override fun visit(name: String, value: Any?) {
            into[name] = annotationValue(value)
        }

        override fun visitEnum(name: String, descriptor: String, value: String) {
            into[name] = value
        }

        override fun visitArray(name: String): AnnotationVisitor {
            val items = mutableListOf<Any?>()
            into[name] = items
            return object : AnnotationVisitor(Opcodes.ASM9) {
                override fun visit(name: String?, value: Any?) {
                    items.add(annotationValue(value))
                }

                override fun visitEnum(name: String?, descriptor: String, value: String) {
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

        override fun visitAnnotation(name: String, descriptor: String): AnnotationVisitor {
            val values = mutableMapOf<String, Any?>()
            into[name] = mapOf("annotation" to descriptor, "values" to values)
            return annotationValues(values)
        }
    }

internal fun readClass(bytes: ByteArray): ClassApi {
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

            override fun visitSource(source: String?, debug: String?) {
                facts.sourceFile = source
            }

            override fun visitAnnotation(descriptor: String, visible: Boolean): AnnotationVisitor {
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

internal fun decode(facts: ClassApi): KotlinClassMetadata? {
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

internal fun readClasses(bytes: ByteArray): Map<String, ClassApi> {
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
    return classes
}

/** The actual unbox method, not a handwritten Kotlin-type/primitive table. */
internal fun valueClassAbi(classes: Map<String, ClassApi>): Map<String, String> = classes
    .mapNotNull { (owner, facts) ->
        val parsed = decode(facts) as? KotlinClassMetadata.Class
        if (parsed?.kmClass?.inlineClassUnderlyingType == null) return@mapNotNull null
        val unbox =
            facts.methods.singleOrNull {
                it.name == "unbox-impl" && it.descriptor.startsWith("()")
            } ?: return@mapNotNull null
        owner to unbox.descriptor.removePrefix("()")
    }.toMap()

/** Some interface metadata omits the physical value-class JVM signature. */
internal fun KmFunction.jvmSignature(
    facts: ClassApi,
    valueClasses: Map<String, String>,
    siblings: List<KmFunction>,
): JvmMethodSignature? = signature?.let { declared ->
    valueClassSignature(declared, facts, valueClasses, siblings)
        ?: declared
}

/**
 * The bytecode method a declaration with a missing physical signature compiles
 * to: its name mangled, its value-class parameters lowered to their ABI.
 */
private fun KmFunction.valueClassSignature(
    declared: JvmMethodSignature,
    facts: ClassApi,
    valueClasses: Map<String, String>,
    siblings: List<KmFunction>,
): JvmMethodSignature? {
    val lowered =
        loweredDescriptor(valueClasses)?.takeIf {
            facts.method(declared) == null &&
                declared.name == name &&
                it != declared.descriptor &&
                // A native sibling with the same ABI must not lend its identity to a
                // declaration whose own signature is missing.
                siblings.count { sibling ->
                    sibling.name == name &&
                        sibling.loweredDescriptor(valueClasses) == it
                } ==
                1
        } ?: return null
    return facts.methods
        .singleOrNull {
            it.name.startsWith(declared.name + "-") &&
                it.descriptor == lowered &&
                it.access and (Opcodes.ACC_SYNTHETIC or Opcodes.ACC_BRIDGE) == 0
        }?.let { JvmMethodSignature(it.name, it.descriptor) }
}

@OptIn(ExperimentalContextReceivers::class)
internal fun KmFunction.loweredDescriptor(valueClasses: Map<String, String>): String? {
    val declared = signature?.takeUnless { isSuspend } ?: return null
    val types =
        contextReceiverTypes + listOfNotNull(receiverParameterType) +
            valueParameters.map { it.type }
    val arguments = org.objectweb.asm.Type.getArgumentTypes(declared.descriptor)

    fun lower(type: KmType, descriptor: String): String {
        val name = (type.classifier as? KmClassifier.Class)?.name?.replace('.', '$')
        return if (!type.isNullable &&
            descriptor == "L$name;"
        ) {
            valueClasses[name] ?: descriptor
        } else {
            descriptor
        }
    }
    val returns = org.objectweb.asm.Type.getReturnType(declared.descriptor).descriptor
    return if (types.size != arguments.size) {
        null
    } else {
        types.zip(arguments).joinToString("", "(", ")") { (type, argument) ->
            lower(type, argument.descriptor)
        } +
            lower(returnType, returns)
    }
}
