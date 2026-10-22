// Development-only compiler frontend. Emit data, never source-expression strings.
@file:Suppress("DEPRECATION_ERROR")
@file:OptIn(org.jetbrains.kotlin.K1Deprecation::class)

import com.google.gson.JsonObject
import org.jetbrains.kotlin.com.intellij.psi.util.PsiTreeUtil
import org.jetbrains.kotlin.descriptors.CallableDescriptor
import org.jetbrains.kotlin.descriptors.ClassDescriptor
import org.jetbrains.kotlin.descriptors.ClassKind
import org.jetbrains.kotlin.descriptors.DeclarationDescriptor
import org.jetbrains.kotlin.descriptors.FunctionDescriptor
import org.jetbrains.kotlin.descriptors.ValueParameterDescriptor
import org.jetbrains.kotlin.psi.KtCallExpression
import org.jetbrains.kotlin.psi.KtDeclaration
import org.jetbrains.kotlin.psi.KtDotQualifiedExpression
import org.jetbrains.kotlin.psi.KtElement
import org.jetbrains.kotlin.psi.KtExpression
import org.jetbrains.kotlin.psi.KtNameReferenceExpression
import org.jetbrains.kotlin.psi.KtNamedFunction
import org.jetbrains.kotlin.resolve.BindingContext
import org.jetbrains.kotlin.resolve.calls.util.getResolvedCall
import org.jetbrains.kotlin.types.KotlinType

/** Drive evidence for a holder's suspend member; nothing for any other target. */
internal fun driveEvidence(
    target: JsonObject,
    declarations: List<Pair<KtDeclaration, CallableDescriptor>>,
    context: BindingContext,
): Map<String, Any?> {
    if (target["suspend"]?.asBoolean != true || target["dispatchReceiver"].isJsonNull) {
        return emptyMap()
    }
    val function = declarations.singleOrNull {
        it.second.matches(target)
    }?.first as? KtNamedFunction
    return mapOf(
        "drive" to
            (function?.let { drive(it, context) } ?: unknown("source/signature disagreement")),
    )
}

/**
 * The anchor a holder's suspend member drives to, read from its pinned body.
 *
 * A drive is the body's one suspend call taking an enum argument. Its target is
 * either a constant enum entry or the member's own parameter; a computed target,
 * no such call, or several of them is unknown, never guessed. Guards such as
 * `confirmValueChange(...)` are not suspend calls and do not count.
 */
private fun drive(function: KtNamedFunction, context: BindingContext): Map<String, Any?> {
    val drives = function.bodyExpression?.let { anchorDrives(it, context) }.orEmpty()
    val (callee, argument) = drives.singleOrNull() ?: return unknown("${drives.size} anchor drives")
    val target = referenceTarget(argument, context)
    return when {
        target is ClassDescriptor && target.kind == ClassKind.ENUM_ENTRY ->
            mapOf("kind" to "constant", "anchor" to target.symbol(), "callee" to callee)
        target is ValueParameterDescriptor &&
            target.containingDeclaration == context[BindingContext.FUNCTION, function] ->
            mapOf("kind" to "parameter", "parameter" to target.name.asString(), "callee" to callee)
        else -> unknown("computed target")
    }
}

/** Every suspend call in [body] taking exactly one enum argument, with its callee. */
private fun anchorDrives(
    body: KtElement,
    context: BindingContext,
): List<Pair<String, KtExpression>> =
    PsiTreeUtil.collectElementsOfType(body, KtCallExpression::class.java).mapNotNull { call ->
        val resolved = call.getResolvedCall(context)
        val callee = resolved?.resultingDescriptor as? FunctionDescriptor
        val anchor =
            resolved?.valueArguments?.values
                ?.flatMap { it.arguments }
                ?.mapNotNull { it.getArgumentExpression() }
                ?.singleOrNull { context.getType(it)?.isEnum() == true }
        if (callee?.isSuspend == true && anchor != null) callee.symbol() to anchor else null
    }

private fun referenceTarget(
    argument: KtExpression,
    context: BindingContext,
): DeclarationDescriptor? {
    val selector = (argument as? KtDotQualifiedExpression)?.selectorExpression ?: argument
    return (selector as? KtNameReferenceExpression)?.let {
        context[BindingContext.REFERENCE_TARGET, it]
    }
}

private fun KotlinType.isEnum(): Boolean =
    (constructor.declarationDescriptor as? ClassDescriptor)?.kind == ClassKind.ENUM_CLASS

private fun unknown(reason: String): Map<String, Any?> = mapOf(
    "kind" to "unknown",
    "reason" to reason,
)
