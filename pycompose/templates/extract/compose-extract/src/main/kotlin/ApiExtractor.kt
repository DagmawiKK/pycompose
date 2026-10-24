import kotlinx.metadata.ClassKind
import kotlinx.metadata.ExperimentalContextReceivers
import kotlinx.metadata.KmClassifier
import kotlinx.metadata.KmConstructor
import kotlinx.metadata.KmDeclarationContainer
import kotlinx.metadata.KmFunction
import kotlinx.metadata.KmProperty
import kotlinx.metadata.Visibility
import kotlinx.metadata.isInline
import kotlinx.metadata.isSuspend
import kotlinx.metadata.jvm.JvmFieldSignature
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
import org.objectweb.asm.Opcodes

/** The library composables that provide context rather than render a component. */
private val CONTEXT_PROVIDERS = setOf("MaterialTheme", "ProvideTextStyle")

/** One class or file facade being read, with what every member inherits from it. */
private class Owner(
    val name: String,
    val facts: ClassApi,
    val parsed: KotlinClassMetadata?,
    val container: KmDeclarationContainer,
    val visibility: Visibility,
    val annotations: Map<String, MutableMap<String, Any?>>,
) {
    val isClass get() = parsed is KotlinClassMetadata.Class
    val dispatchReceiver get() = if (isClass) classType(name).document() else null

    /** The fields every declaration of this owner shares, in document order. */
    fun header(coordinate: String, name: String, kind: String) = mapOf(
        "artifact" to coordinate,
        "owner" to this.name.replace('/', '.'),
        "package" to this.name.substringBeforeLast('/').replace('/', '.'),
        "name" to name,
        "declarationKind" to kind,
    )
}

internal class ApiExtractor(
    private val coordinate: String,
    // Whether this artifact's group contributes components (compose-closure.json).
    val components: Boolean,
    private val diagnostics: MutableList<Map<String, Any?>>,
    private val valueClasses: Map<String, String>,
) {
    /** One artifact's public API plus the class facts its hierarchy needs. */
    class Extracted(
        val declarations: List<Map<String, Any?>>,
        val classes: List<Map<String, Any?>>,
    )

    fun extract(classes: Map<String, ClassApi>): Extracted {
        val metadata = classes.mapValues { (_, facts) -> decode(facts) }
        val declarations = mutableListOf<Map<String, Any?>>()
        for ((name, facts) in classes) {
            val parsed = metadata[name]
            val container: KmDeclarationContainer =
                when (parsed) {
                    is KotlinClassMetadata.Class -> parsed.kmClass
                    is KotlinClassMetadata.FileFacade -> parsed.kmPackage
                    is KotlinClassMetadata.MultiFileClassPart -> parsed.kmPackage
                    // Multifile facades delegate to their parts; synthetic lambda
                    // classes are implementations, not additional public APIs.
                    else -> continue
                }
            val chain = enclosingChain(name)
            val owner =
                Owner(
                    name,
                    facts,
                    parsed,
                    container,
                    visibilityOf(chain, metadata),
                    annotationsOf(chain, classes),
                )
            container.functions.mapTo(declarations) { function(owner, it) }
            container.properties.mapTo(declarations) { property(owner, it, classes) }
            (parsed as? KotlinClassMetadata.Class)?.kmClass?.constructors?.mapTo(declarations) {
                constructor(owner, it)
            }
            if (components && owner.visibility == Visibility.PUBLIC) auditBytecode(owner)
        }
        return Extracted(
            declarations.map { withClassFacts(it, classes, metadata) },
            classEvidence(classes, metadata),
        )
    }

    @OptIn(ExperimentalContextReceivers::class)
    private fun function(owner: Owner, function: KmFunction): Map<String, Any?> {
        val facts = owner.facts
        val signature = function.jvmSignature(facts, valueClasses, owner.container.functions)
        val method = facts.method(signature)
        val annotations =
            (owner.annotations + method?.annotations.orEmpty())
                .filterKeys { it != "kotlin/Metadata" }
        val composable = annotations.containsKey(COMPOSE_ANNOTATION)
        val eligibility = exclusion(function.visibility, owner.visibility, annotations)
        val reason = eligibility ?: methodExclusion(method)
        if (eligibility == null && method == null) {
            report("${owner.name}.${function.name}: unmatched $signature")
        }
        val returnsUnit =
            (function.returnType.classifier as? KmClassifier.Class)?.name == "kotlin/Unit"
        val contextProvider = function.name in CONTEXT_PROVIDERS
        return owner.header(coordinate, function.name, "function") +
            mapOf(
                "suspend" to function.isSuspend,
                // An inline call compiles into its body, so no call to
                // this identity appears in the caller's bytecode.
                "inline" to function.isInline,
                "visibility" to function.visibility.name,
                "classVisibility" to owner.visibility.name,
                "jvm" to facts.jvm(signature),
                "disposition" to
                    when {
                        eligibility == null && method == null -> "error"
                        reason != null -> "excluded"
                        components && composable && returnsUnit && !contextProvider -> "ui"
                        else -> "support"
                    },
                "category" to category(reason, composable, returnsUnit, contextProvider),
                "reason" to reason,
                "composable" to composable,
                "annotations" to annotations,
                "receiver" to function.receiverParameterType?.document(),
                "dispatchReceiver" to owner.dispatchReceiver,
                "contextReceivers" to function.contextReceiverTypes.map { it.document() },
                "returnType" to function.returnType.document(),
                "typeParameters" to function.typeParameters.map { it.document() },
                "parameters" to function.valueParameters.map { it.document() },
            )
    }

    private fun accessor(
        owner: Owner,
        signature: JvmMethodSignature?,
        visibility: Visibility?,
    ): Map<String, Any?>? = signature?.let {
        val method = owner.facts.method(it)
        val annotations = owner.annotations + method?.annotations.orEmpty()
        val reason =
            when {
                visibility == null -> "missing accessor visibility"
                exclusion(visibility, owner.visibility, annotations) != null ->
                    exclusion(visibility, owner.visibility, annotations)
                method == null -> "unmatched accessor"
                method.access and Opcodes.ACC_PUBLIC == 0 -> "non-public JVM accessor"
                else -> null
            }
        owner.facts.jvm(it) +
            mapOf(
                "visibility" to visibility?.name,
                "access" to method?.access,
                "callable" to (reason == null),
                "reason" to reason,
            )
    }

    @OptIn(ExperimentalContextReceivers::class)
    private fun property(
        owner: Owner,
        property: KmProperty,
        classes: Map<String, ClassApi>,
    ): Map<String, Any?> {
        val facts = owner.facts
        val getter = accessor(owner, property.getterSignature, property.getter.visibility)
        val setter = accessor(owner, property.setterSignature, property.setter?.visibility)
        val field = property.fieldSignature?.let { field(owner, it, classes) }
        val methods =
            listOfNotNull(
                property.getterSignature,
                property.setterSignature,
                property.syntheticMethodForAnnotations,
            ).mapNotNull { facts.method(it) }
        val annotations =
            (
                owner.annotations +
                    methods.flatMap { it.annotations.entries }.associate { it.toPair() }
                )
                .filterKeys { it != "kotlin/Metadata" }
        val eligibility = exclusion(property.visibility, owner.visibility, annotations)
        val matched = getter?.get("matched") == true || field != null
        val unreadAccessor =
            listOfNotNull(getter, setter).any {
                it["visibility"] == "PUBLIC" &&
                    it["matched"] != true
            }
        val unmatched = eligibility == null && (!matched || unreadAccessor)
        val reason = eligibility ?: UNMATCHED_PROPERTY.takeIf { unmatched }
        if (unmatched) report("${owner.name}.${property.name}: $reason")
        return owner.header(coordinate, property.name, "property") +
            mapOf(
                "visibility" to property.visibility.name,
                "classVisibility" to owner.visibility.name,
                "jvm" to (
                    getter ?: mapOf(
                        "name" to property.fieldSignature?.name,
                        "descriptor" to property.fieldSignature?.descriptor,
                        "matched" to matched,
                    )
                    ),
                "accessors" to mapOf("getter" to getter, "setter" to setter),
                "constant" to field?.second,
                "disposition" to disposition(reason, UNMATCHED_PROPERTY),
                "reason" to reason,
                "composable" to annotations.containsKey(COMPOSE_ANNOTATION),
                "annotations" to annotations,
                "receiver" to property.receiverParameterType?.document(),
                "dispatchReceiver" to owner.dispatchReceiver,
                "contextReceivers" to property.contextReceiverTypes.map { it.document() },
                "returnType" to property.returnType.document(),
                "parameters" to emptyList<Any>(),
                "typeParameters" to property.typeParameters.map { it.document() },
            )
    }

    private fun constructor(owner: Owner, constructor: KmConstructor): Map<String, Any?> {
        val signature = constructor.signature
        val method = owner.facts.method(signature)
        val annotations =
            (owner.annotations + method?.annotations.orEmpty())
                .filterKeys { it != "kotlin/Metadata" }
        val annotationClass =
            (owner.parsed as KotlinClassMetadata.Class).kmClass.kind == ClassKind.ANNOTATION_CLASS
        val reason =
            exclusion(constructor.visibility, owner.visibility, annotations)
                ?: when {
                    annotationClass -> "annotation constructors are not JVM callables"
                    method == null -> UNMATCHED_CONSTRUCTOR
                    else -> null
                }
        if (reason == UNMATCHED_CONSTRUCTOR) report("${owner.name}: $reason")
        return owner.header(coordinate, "<init>", "constructor") +
            mapOf(
                "visibility" to constructor.visibility.name,
                "classVisibility" to owner.visibility.name,
                "jvm" to owner.facts.jvm(signature),
                "disposition" to disposition(reason, UNMATCHED_CONSTRUCTOR),
                "reason" to reason,
                "composable" to false,
                "annotations" to annotations,
                "receiver" to null,
                "dispatchReceiver" to null,
                "contextReceivers" to emptyList<Any>(),
                "returnType" to classType(owner.name).document(),
                "typeParameters" to emptyList<Any>(),
                "parameters" to constructor.valueParameters.map { it.document() },
            )
    }

    /** Composable bytecode that metadata does not declare is a reader bug, not API. */
    private fun auditBytecode(owner: Owner) {
        val container = owner.container
        val metadataSignatures =
            container.functions.mapNotNull {
                it.jvmSignature(owner.facts, valueClasses, container.functions)
            } +
                container.properties.flatMap {
                    listOfNotNull(
                        it.getterSignature,
                        it.setterSignature,
                        it.syntheticMethodForAnnotations,
                    )
                }
        owner.facts.methods
            .filter { m ->
                COMPOSE_ANNOTATION in m.annotations &&
                    m.access and Opcodes.ACC_PUBLIC != 0 &&
                    m.access and (Opcodes.ACC_SYNTHETIC or Opcodes.ACC_BRIDGE) == 0 &&
                    metadataSignatures.none { it.name == m.name && it.descriptor == m.descriptor }
            }.forEach { m ->
                diagnostics.add(
                    mapOf(
                        "target" to true,
                        "unmatchedBytecode" to true,
                        "message" to
                            "$coordinate ${owner.name}.${m.name}${m.descriptor}: " +
                            "annotated bytecode has no metadata declaration",
                    ),
                )
            }
    }

    private fun report(message: String) {
        diagnostics.add(mapOf("target" to components, "message" to "$coordinate $message"))
    }

    /**
     * Declaration-free classes carry no members, but the wire still needs their
     * hierarchy: Alignment.Vertical is only a subtype of Alignment because the
     * class itself says so.
     */
    private fun classEvidence(
        classes: Map<String, ClassApi>,
        metadata: Map<String, KotlinClassMetadata?>,
    ): List<Map<String, Any?>> = classes.mapNotNull { (owner, facts) ->
        val kmClass =
            (metadata[owner] as? KotlinClassMetadata.Class)?.kmClass ?: return@mapNotNull null
        val chain = enclosingChain(owner)
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
        )
    }
}

private const val UNMATCHED_PROPERTY = "unmatched property accessor/field"
private const val UNMATCHED_CONSTRUCTOR = "unmatched constructor"

/** A member's disposition: an evidence error, an exclusion, or support. */
private fun disposition(reason: String?, unmatched: String): String = when (reason) {
    unmatched -> "error"
    null -> "support"
    else -> "excluded"
}

/** Why a function's bytecode method cannot be called, if it cannot. */
private fun methodExclusion(method: MethodApi?): String? = when {
    method == null -> "metadata JVM signature has no bytecode method"
    method.access and (Opcodes.ACC_SYNTHETIC or Opcodes.ACC_BRIDGE) != 0 ->
        "synthetic or bridge method"
    method.access and Opcodes.ACC_PUBLIC == 0 -> "non-public JVM method"
    else -> null
}

/**
 * A property's backing field. Kotlin companion @JvmField/const properties are
 * physically emitted on the enclosing class, not on the Companion class.
 */
private fun field(
    owner: Owner,
    signature: JvmFieldSignature,
    classes: Map<String, ClassApi>,
): Pair<Int, Any?>? {
    val companion =
        (owner.parsed as? KotlinClassMetadata.Class)?.kmClass?.kind ==
            ClassKind.COMPANION_OBJECT
    val enclosing = owner.name.substringBeforeLast('$')
    val fieldOwner = if (companion) classes[enclosing] else owner.facts
    val key = signature.name to signature.descriptor
    return owner.facts.fields[key] ?: fieldOwner?.fields?.get(key)
}

private fun withClassFacts(
    declaration: Map<String, Any?>,
    classes: Map<String, ClassApi>,
    metadata: Map<String, KotlinClassMetadata?>,
): Map<String, Any?> {
    val owner = declaration["owner"].toString().replace('.', '/')
    val kmClass = (metadata[owner] as? KotlinClassMetadata.Class)?.kmClass
    return declaration +
        mapOf(
            "sourceFile" to classes[owner]?.sourceFile,
            "classKind" to kmClass?.kind?.name,
            // Modality decides whether a constructor is callable at all: an
            // abstract class exposes one that can never be invoked.
            "classModality" to kmClass?.modality?.name,
            "enumEntries" to kmClass?.enumEntries.orEmpty(),
            "enclosingTypeParameters" to kmClass?.typeParameters.orEmpty().map {
                it.document()
            },
            "classSupertypes" to kmClass?.supertypes.orEmpty().map { it.document() },
        )
}

/** The class itself followed by every enclosing class or file facade. */
private fun enclosingChain(owner: String): List<String> = generateSequence(owner) {
    if ('$' in it) it.substringBeforeLast('$') else null
}.toList()

/** The most restrictive visibility anywhere in the enclosing chain. */
private fun visibilityOf(
    chain: List<String>,
    metadata: Map<String, KotlinClassMetadata?>,
): Visibility = chain
    .mapNotNull { (metadata[it] as? KotlinClassMetadata.Class)?.kmClass?.visibility }
    .firstOrNull { it != Visibility.PUBLIC } ?: Visibility.PUBLIC

/** Annotations declared anywhere in the enclosing chain, minus stdlib noise. */
private fun annotationsOf(
    chain: List<String>,
    classes: Map<String, ClassApi>,
): Map<String, MutableMap<String, Any?>> = chain
    .flatMap { classes[it]?.annotations.orEmpty().entries }
    .associate { it.toPair() }
    .filterKeys { it != "kotlin/Metadata" }

/** What a function is for, before the component rule decides its disposition. */
private fun ApiExtractor.category(
    reason: String?,
    composable: Boolean,
    returnsUnit: Boolean,
    contextProvider: Boolean,
): String = when {
    reason != null -> "excluded"
    !components -> "support"
    contextProvider -> "composition-provider"
    composable && !returnsUnit -> "composable-factory"
    else -> "component"
}
