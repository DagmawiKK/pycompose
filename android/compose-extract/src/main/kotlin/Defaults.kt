// Development-only compiler frontend. Emit data, never source-expression strings.
@file:Suppress("DEPRECATION_ERROR")
@file:OptIn(
    org.jetbrains.kotlin.CoreEnvironmentDeprecation::class,
    org.jetbrains.kotlin.K1Deprecation::class,
    org.jetbrains.kotlin.compiler.plugin.ExperimentalCompilerApi::class,
    org.jetbrains.kotlin.config.CompilerConfiguration.Internals::class,
    org.jetbrains.kotlin.config.MessageCollectorAccess::class,
)

import org.jetbrains.kotlin.config.CompilerConfiguration
import org.jetbrains.kotlin.descriptors.ClassDescriptor
import org.jetbrains.kotlin.descriptors.ClassKind
import org.jetbrains.kotlin.descriptors.ConstructorDescriptor
import org.jetbrains.kotlin.descriptors.PropertyDescriptor
import org.jetbrains.kotlin.diagnostics.Severity
import org.jetbrains.kotlin.psi.KtCallExpression
import org.jetbrains.kotlin.psi.KtConstantExpression
import org.jetbrains.kotlin.psi.KtDotQualifiedExpression
import org.jetbrains.kotlin.psi.KtExpression
import org.jetbrains.kotlin.psi.KtLambdaExpression
import org.jetbrains.kotlin.psi.KtNameReferenceExpression
import org.jetbrains.kotlin.psi.KtParenthesizedExpression
import org.jetbrains.kotlin.psi.KtPrefixExpression
import org.jetbrains.kotlin.psi.KtProperty
import org.jetbrains.kotlin.psi.KtStringTemplateExpression
import org.jetbrains.kotlin.resolve.BindingContext
import org.jetbrains.kotlin.resolve.DescriptorToSourceUtils
import org.jetbrains.kotlin.resolve.calls.util.getResolvedCall
import org.jetbrains.kotlin.types.KotlinType
import org.jetbrains.kotlin.types.checker.KotlinTypeChecker

private const val MAX_TOKEN_DEPTH = 32
private val TOKEN_UNIT_CONVERSIONS = setOf(
    "androidx.compose.ui.unit.dp",
    "androidx.compose.ui.unit.sp",
    "androidx.compose.ui.unit.em",
)

internal class Defaults(private val context: BindingContext) {
    private val resolving = mutableSetOf<String>()

    /** Token symbols whose declaring source file has not been analysed yet. */
    val missing = linkedSetOf<String>()
    internal fun expression(node: KtExpression): Map<String, Any?> {
        check(
            context.diagnostics.all().none {
                it.severity == Severity.ERROR &&
                    it.psiElement.containingFile == node.containingFile &&
                    node.textRange.contains(it.psiElement.textRange)
            },
        ) { "compiler error in default expression" }
        val type = context.getType(node) ?: error("unresolved default type")
        val reference = when (node) {
            is KtNameReferenceExpression -> node
            is KtDotQualifiedExpression -> node.selectorExpression as? KtNameReferenceExpression
            else -> null
        }
        val call = (node as? KtCallExpression)
            ?: (node as? KtDotQualifiedExpression)?.selectorExpression as? KtCallExpression
        return when {
            node is KtParenthesizedExpression -> expression(node.expression!!)
            node is KtConstantExpression || node is KtPrefixExpression -> literal(node, type)
            reference != null -> property(node, reference, type)
            call != null -> call(call, node)
            else -> template(node, type)
        }
    }

    /**
     * A constant string (`label: String = "AnimatedContent"`), or an empty lambda
     * (`content: @Composable () -> Unit = {}`, a slot that draws nothing); nothing else.
     */
    private fun template(node: KtExpression, type: KotlinType): Map<String, Any?> {
        val constant = context[BindingContext.COMPILE_TIME_VALUE, node]
            ?.takeUnless { it.isError }?.getValue(type)
        if (node is KtStringTemplateExpression && constant is String) {
            return mapOf("kind" to "literal", "type" to type.classifier(), "value" to constant)
        }
        check(node is KtLambdaExpression && node.bodyExpression?.statements.isNullOrEmpty()) {
            "unsupported default syntax: ${node.javaClass.simpleName}"
        }
        return mapOf("kind" to "emptyLambda")
    }

    private fun literal(node: KtExpression, type: KotlinType): Map<String, Any?> {
        val value = context[BindingContext.COMPILE_TIME_VALUE, node]
            ?.takeUnless { it.isError }?.getValue(type)
        check(value == null || value is Number || value is Boolean) { "unsupported literal" }
        check(value != null || node.text == "null") { "unresolved literal" }
        return mapOf("kind" to "literal", "type" to type.classifier(), "value" to value)
    }

    private fun property(
        node: KtExpression,
        reference: KtNameReferenceExpression,
        type: KotlinType,
    ): Map<String, Any?> {
        val target = context[BindingContext.REFERENCE_TARGET, reference]
        if (target is ClassDescriptor && target.kind == ClassKind.OBJECT) {
            check(resolving.isEmpty() && target.exported()) { "non-public/token object default" }
            staticQualifier(node)
            return mapOf("kind" to "object", "symbol" to target.symbol())
        }
        val property = target as? PropertyDescriptor
            ?: error("default is not a resolved property")
        check(!property.isVar) { "mutable default reference" }
        val receiver = (node as? KtDotQualifiedExpression)?.receiverExpression
        val qualifier =
            receiver != null && context[BindingContext.QUALIFIER, receiver] != null
        requireStaticQualifier(property, receiver, qualifier, node)
        // A property reference is only safe when it really is the value the
        // parameter declares; anything else is a protocol, not a default.
        check(KotlinTypeChecker.DEFAULT.equalTypes(property.type, type)) {
            "default ${property.symbol()} is not a ${type.classifier()}"
        }
        return memberValue(property, receiver, qualifier, node, type)
    }

    /**
     * Keep reduction and rendering behind a static qualifier.
     *
     * A non-extension member read is reduced to its initializer (tokens) or
     * rendered (composed values); reducing is only sound behind a static
     * qualifier, so anything else must stay out of token resolution.
     */
    private fun requireStaticQualifier(
        property: PropertyDescriptor,
        receiver: KtExpression?,
        qualifier: Boolean,
        node: KtExpression,
    ) {
        val staticAccess = receiver == null || qualifier
        if (property.extensionReceiverParameter == null &&
            (staticAccess || resolving.isNotEmpty())
        ) {
            staticQualifier(node)
        }
    }

    /** Render or reduce a member read whose receiver and type already passed. */
    private fun memberValue(
        property: PropertyDescriptor,
        receiver: KtExpression?,
        qualifier: Boolean,
        node: KtExpression,
        type: KotlinType,
    ): Map<String, Any?> = when {
        // Internal immutable token aliases may be reduced from the pinned
        // source, never referenced from shipped Kotlin. Do not execute
        // arbitrary getters or turn their bodies into expression strings.
        !property.exported() -> token(property)
        resolving.isNotEmpty() && property.isConst -> literal(node, type)
        property.extensionReceiverParameter != null -> {
            val symbol = property.symbol()
            check(resolving.isEmpty() || symbol in TOKEN_UNIT_CONVERSIONS) {
                "unproven conversion in token initializer"
            }
            mapOf(
                "kind" to "extensionProperty",
                "symbol" to symbol,
                "receiver" to expression(
                    receiver ?: error("implicit extension receiver in default"),
                ),
            )
        }
        receiver != null && !qualifier -> {
            // A public member read on an already-representable receiver, such as
            // MaterialTheme.colorScheme.primary. The chain stays native and is
            // evaluated during composition; nothing here is pre-resolved.
            check(resolving.isEmpty()) { "computed reference in token initializer" }
            mapOf(
                "kind" to "memberProperty",
                "symbol" to property.symbol(),
                "receiver" to expression(receiver),
            )
        }
        else -> {
            check(resolving.isEmpty()) { "computed reference in token initializer" }
            check(property.staticReceiver()) {
                "instance property default: ${property.symbol()}"
            }
            mapOf("kind" to "property", "symbol" to property.symbol())
        }
    }

    private fun token(property: PropertyDescriptor): Map<String, Any?> {
        check(property.staticReceiver()) { "instance token default" }
        val declaration = DescriptorToSourceUtils.descriptorToDeclaration(property) as? KtProperty
            ?: run {
                missing.add(property.symbol())
                error("missing token source: ${property.symbol()}")
            }
        check(declaration.getter == null && !declaration.hasDelegate()) { "computed token default" }
        val initializer = declaration.initializer ?: error("missing token initializer")
        check(resolving.size < MAX_TOKEN_DEPTH && resolving.add(property.symbol())) {
            "cyclic/deep token default"
        }
        return try {
            expression(initializer)
        } finally {
            resolving.remove(property.symbol())
        }
    }

    private fun staticQualifier(node: KtExpression) {
        if (node is KtDotQualifiedExpression) {
            check(context[BindingContext.QUALIFIER, node.receiverExpression] != null) {
                "computed qualifier in default"
            }
        }
    }

    private fun call(call: KtCallExpression, node: KtExpression): Map<String, Any?> {
        check(resolving.isEmpty()) { "call in token initializer" }
        staticQualifier(node)
        val resolved = call.getResolvedCall(context) ?: error("unresolved default call")
        check(resolved.status.isSuccess) { "ambiguous/invalid default call" }
        val target = resolved.resultingDescriptor
        check(target.exported() && target.extensionReceiverParameter == null) {
            "non-public/extension default call"
        }
        check(target is ConstructorDescriptor || target.staticReceiver()) {
            "instance default call"
        }
        // Only a zero-argument call is a reusable policy. Anything with
        // arguments would smuggle per-binding Kotlin back into the schema.
        check(
            call.valueArguments.isEmpty() &&
                call.lambdaArguments.isEmpty() &&
                resolved.valueArguments.values.all { it.arguments.isEmpty() },
        ) { "default call takes arguments" }
        val symbol = if (target is ConstructorDescriptor) {
            target.containingDeclaration.symbol()
        } else {
            target.symbol()
        }
        return mapOf("kind" to "call", "symbol" to symbol)
    }
}
