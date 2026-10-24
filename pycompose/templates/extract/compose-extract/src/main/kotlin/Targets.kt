// Development-only compiler frontend. Emit data, never source-expression strings.
@file:Suppress("DEPRECATION_ERROR")
@file:OptIn(
    org.jetbrains.kotlin.CoreEnvironmentDeprecation::class,
    org.jetbrains.kotlin.K1Deprecation::class,
    org.jetbrains.kotlin.compiler.plugin.ExperimentalCompilerApi::class,
    org.jetbrains.kotlin.config.CompilerConfiguration.Internals::class,
    org.jetbrains.kotlin.config.MessageCollectorAccess::class,
)

import com.google.gson.JsonObject
import org.jetbrains.kotlin.config.CompilerConfiguration
import org.jetbrains.kotlin.descriptors.CallableDescriptor
import org.jetbrains.kotlin.descriptors.ClassDescriptor
import org.jetbrains.kotlin.descriptors.ClassKind
import org.jetbrains.kotlin.descriptors.ClassifierDescriptorWithTypeParameters
import org.jetbrains.kotlin.descriptors.ConstructorDescriptor
import org.jetbrains.kotlin.descriptors.DeclarationDescriptor
import org.jetbrains.kotlin.descriptors.DeclarationDescriptorWithVisibility
import org.jetbrains.kotlin.descriptors.DescriptorVisibilities
import org.jetbrains.kotlin.descriptors.MemberDescriptor
import org.jetbrains.kotlin.descriptors.PackageFragmentDescriptor
import org.jetbrains.kotlin.psi.KtDeclaration
import org.jetbrains.kotlin.psi.KtParameter
import org.jetbrains.kotlin.resolve.DescriptorToSourceUtils
import org.jetbrains.kotlin.resolve.DescriptorUtils
import org.jetbrains.kotlin.resolve.descriptorUtil.classId
import org.jetbrains.kotlin.types.KotlinType

internal fun DeclarationDescriptor.symbol(): String = DescriptorUtils.getFqNameSafe(this).asString()

internal fun KotlinType.classifier(): String {
    val descriptor = checkNotNull(constructor.declarationDescriptor)
    // Metadata's spelling, which the inventory records: '/' between package
    // segments and '.' between nested classes (Arrangement.Horizontal).
    return (descriptor as? ClassifierDescriptorWithTypeParameters)?.classId?.asString()
        ?: descriptor.symbol().replace('.', '/')
}

internal fun KotlinType.matches(type: JsonObject): Boolean {
    val expectedArguments = type.getAsJsonArray("arguments")
    return classifier() == type["classifier"].asString &&
        isMarkedNullable == type["nullable"].asBoolean &&
        arguments.size == expectedArguments.size() &&
        arguments.zip(expectedArguments).all { (actual, expected) ->
            !actual.isStarProjection &&
                !expected.asJsonObject["type"].isJsonNull &&
                actual.type.matches(expected.asJsonObject.getAsJsonObject("type"))
        }
}

internal fun DeclarationDescriptor.exported(): Boolean =
    (this !is DeclarationDescriptorWithVisibility || visibility == DescriptorVisibilities.PUBLIC) &&
        (containingDeclaration?.let { it !is PackageFragmentDescriptor && !it.exported() } != true)

internal fun CallableDescriptor.staticReceiver(): Boolean = dispatchReceiverParameter == null ||
    (containingDeclaration as? ClassDescriptor)?.kind == ClassKind.OBJECT

internal fun targetSymbol(target: JsonObject): String {
    val owner = target["owner"].asString.replace('$', '.')
    val holder = if (!target["dispatchReceiver"].isJsonNull) owner else target["package"].asString
    return if (target["declarationKind"].asString == "constructor") {
        owner
    } else {
        holder + "." + target["name"].asString
    }
}

internal fun CallableDescriptor.matches(target: JsonObject, defaults: Boolean = true): Boolean {
    val parameters = target.getAsJsonArray("parameters")
    val identity = if (this is ConstructorDescriptor) containingDeclaration.symbol() else symbol()
    val receiver = target["receiver"]
    val receiverMatches = if (receiver.isJsonNull) {
        extensionReceiverParameter == null
    } else {
        extensionReceiverParameter?.type?.matches(receiver.asJsonObject) == true
    }
    return identity == targetSymbol(target) &&
        receiverMatches &&
        contextReceiverParameters.size == target.getAsJsonArray("contextReceivers").size() &&
        contextReceiverParameters.zip(
            target.getAsJsonArray("contextReceivers"),
        ).all { (actual, expected) ->
            actual.type.matches(expected.asJsonObject)
        } &&
        (this is ConstructorDescriptor) == (target["declarationKind"].asString == "constructor") &&
        valueParameters.size == parameters.size() &&
        valueParameters.zip(parameters).all { (actual, expected) ->
            actual.name.asString() == expected.asJsonObject["name"].asString &&
                actual.type.matches(expected.asJsonObject.getAsJsonObject("type")) &&
                (
                    !defaults ||
                        actual.declaresDefaultValue() ==
                        expected.asJsonObject["hasDefault"].asBoolean
                    )
        } &&
        returnType?.matches(target.getAsJsonObject("returnType")) == true
}

internal fun resolveTarget(
    target: JsonObject,
    declarations: List<Pair<KtDeclaration, CallableDescriptor>>,
    defaults: Defaults,
): Map<String, Any?> {
    val direct = declarations.filter { (node, descriptor) ->
        descriptor.matches(target) &&
            (
                target["sourceFile"].isJsonNull ||
                    node.containingKtFile.name == target["sourceFile"].asString
                )
    }
    // Android actual declarations inherit defaults from their common expect.
    // Require both an exact platform signature/file and one matching expect;
    // never search by name or borrow another overload's defaults.
    val platform = declarations.filter { (node, descriptor) ->
        (descriptor as? MemberDescriptor)?.isActual == true &&
            descriptor.matches(target, defaults = false) &&
            !target["sourceFile"].isJsonNull &&
            node.containingKtFile.name == target["sourceFile"].asString
    }
    val matches = if (direct.isEmpty() && platform.size == 1) {
        declarations.filter { (_, descriptor) ->
            (descriptor as? MemberDescriptor)?.isExpect == true && descriptor.matches(target)
        }
    } else {
        direct
    }
    val parameters = target.getAsJsonArray("parameters").filter {
        it.asJsonObject["hasDefault"].asBoolean
    }
    val expressions = parameters.associate { parameter ->
        val name = parameter.asJsonObject["name"].asString
        val expression = runCatching {
            check(matches.size == 1) {
                "source/signature disagreement: ${matches.size} matches for " + targetSymbol(target)
            }
            val descriptor = matches.single().second.valueParameters.single {
                it.name.asString() == name
            }
            val psi = DescriptorToSourceUtils.descriptorToDeclaration(descriptor) as? KtParameter
            defaults.expression(psi?.defaultValue ?: error("missing source default"))
        }.getOrElse {
            mapOf("kind" to "unsupported", "reason" to (it.message ?: it.javaClass.simpleName))
        }
        name to expression
    }
    return mapOf(
        "owner" to target["owner"].asString,
        "jvm" to target["jvm"],
        "matched" to (matches.size == 1),
        "defaults" to expressions,
    )
}

/** Every extracted source file, indexed by the symbols it declares. */
