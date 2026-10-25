import kotlinx.metadata.KmAnnotationArgument
import kotlinx.metadata.KmClassifier
import kotlinx.metadata.KmType
import kotlinx.metadata.KmTypeParameter
import kotlinx.metadata.KmValueParameter
import kotlinx.metadata.Visibility
import kotlinx.metadata.declaresDefaultValue
import kotlinx.metadata.isNullable
import kotlinx.metadata.isSuspend
import kotlinx.metadata.jvm.annotations
import kotlinx.metadata.visibility

internal fun KmType.document(): Map<String, Any?> = mapOf(
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

internal fun KmAnnotationArgument.document(): Any? = when (this) {
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

internal fun classType(name: String): KmType =
    KmType().apply { classifier = KmClassifier.Class(name) }

internal fun KmValueParameter.document(): Map<String, Any?> = mapOf(
    "name" to name,
    "type" to type.document(),
    "hasDefault" to declaresDefaultValue,
    "varargType" to varargElementType?.document(),
)

internal fun KmTypeParameter.document(): Map<String, Any?> = mapOf(
    "id" to id,
    "name" to name,
    "variance" to variance.name,
    "bounds" to upperBounds.map { it.document() },
)

internal fun exclusion(
    visibility: Visibility,
    classVisibility: Visibility,
    annotations: Map<String, Map<String, Any?>>,
): String? = when {
    visibility != Visibility.PUBLIC || classVisibility != Visibility.PUBLIC ->
        "non-public Kotlin declaration"
    "androidx/annotation/RestrictTo" in annotations -> "restricted API"
    annotations["kotlin/Deprecated"]?.get(
        "level",
    ) == "HIDDEN" -> "hidden compatibility declaration"
    else -> null
}
