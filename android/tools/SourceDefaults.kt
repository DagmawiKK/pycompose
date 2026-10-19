// Development-only compiler frontend. Emit data, never source-expression strings.
@file:Suppress("DEPRECATION_ERROR")
@file:OptIn(
    org.jetbrains.kotlin.CoreEnvironmentDeprecation::class,
    org.jetbrains.kotlin.K1Deprecation::class,
    org.jetbrains.kotlin.compiler.plugin.ExperimentalCompilerApi::class,
    org.jetbrains.kotlin.config.CompilerConfiguration.Internals::class,
    org.jetbrains.kotlin.config.MessageCollectorAccess::class,
)

import com.google.gson.GsonBuilder
import com.google.gson.JsonObject
import org.jetbrains.kotlin.cli.common.messages.MessageCollector
import org.jetbrains.kotlin.cli.extensionsStorage
import org.jetbrains.kotlin.cli.jvm.compiler.EnvironmentConfigFiles
import org.jetbrains.kotlin.cli.jvm.compiler.KotlinCoreEnvironment
import org.jetbrains.kotlin.cli.jvm.compiler.NoScopeRecordCliBindingTrace
import org.jetbrains.kotlin.cli.jvm.compiler.TopDownAnalyzerFacadeForJVM
import org.jetbrains.kotlin.cli.jvm.config.addJvmClasspathRoots
import org.jetbrains.kotlin.com.intellij.openapi.util.Disposer
import org.jetbrains.kotlin.com.intellij.psi.util.PsiTreeUtil
import org.jetbrains.kotlin.compiler.plugin.CompilerPluginRegistrar.ExtensionStorage
import org.jetbrains.kotlin.config.CommonConfigurationKeys
import org.jetbrains.kotlin.config.CompilerConfiguration
import org.jetbrains.kotlin.descriptors.CallableDescriptor
import org.jetbrains.kotlin.descriptors.ClassDescriptor
import org.jetbrains.kotlin.descriptors.ClassKind
import org.jetbrains.kotlin.descriptors.ConstructorDescriptor
import org.jetbrains.kotlin.descriptors.DeclarationDescriptor
import org.jetbrains.kotlin.descriptors.DeclarationDescriptorWithVisibility
import org.jetbrains.kotlin.descriptors.DescriptorVisibilities
import org.jetbrains.kotlin.descriptors.MemberDescriptor
import org.jetbrains.kotlin.descriptors.PackageFragmentDescriptor
import org.jetbrains.kotlin.descriptors.PropertyDescriptor
import org.jetbrains.kotlin.diagnostics.Severity
import org.jetbrains.kotlin.psi.KtCallExpression
import org.jetbrains.kotlin.psi.KtConstantExpression
import org.jetbrains.kotlin.psi.KtDeclaration
import org.jetbrains.kotlin.psi.KtDotQualifiedExpression
import org.jetbrains.kotlin.psi.KtExpression
import org.jetbrains.kotlin.psi.KtFile
import org.jetbrains.kotlin.psi.KtNameReferenceExpression
import org.jetbrains.kotlin.psi.KtParameter
import org.jetbrains.kotlin.psi.KtParenthesizedExpression
import org.jetbrains.kotlin.psi.KtPrefixExpression
import org.jetbrains.kotlin.psi.KtProperty
import org.jetbrains.kotlin.psi.KtPsiFactory
import org.jetbrains.kotlin.resolve.BindingContext
import org.jetbrains.kotlin.resolve.DescriptorToSourceUtils
import org.jetbrains.kotlin.resolve.DescriptorUtils
import org.jetbrains.kotlin.resolve.calls.util.getResolvedCall
import org.jetbrains.kotlin.types.KotlinType
import org.jetbrains.kotlin.types.checker.KotlinTypeChecker
import java.io.File
import java.util.zip.ZipFile

private fun DeclarationDescriptor.symbol(): String = DescriptorUtils.getFqNameSafe(this).asString()

private fun KotlinType.classifier(): String {
    val descriptor = checkNotNull(constructor.declarationDescriptor)
    return descriptor.symbol().replace('.', '/')
}

private fun KotlinType.matches(type: JsonObject): Boolean {
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

private fun DeclarationDescriptor.exported(): Boolean =
    (this !is DeclarationDescriptorWithVisibility || visibility == DescriptorVisibilities.PUBLIC) &&
        (containingDeclaration?.let { it !is PackageFragmentDescriptor && !it.exported() } != true)

private fun CallableDescriptor.staticReceiver(): Boolean = dispatchReceiverParameter == null ||
    (containingDeclaration as? ClassDescriptor)?.kind == ClassKind.OBJECT

private const val MAX_TOKEN_DEPTH = 32
private val TOKEN_UNIT_CONVERSIONS = setOf(
    "androidx.compose.ui.unit.dp",
    "androidx.compose.ui.unit.sp",
    "androidx.compose.ui.unit.em",
)

private class Defaults(private val context: BindingContext) {
    private val resolving = mutableSetOf<String>()
    fun expression(node: KtExpression): Map<String, Any?> {
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
            else -> error("unsupported default syntax: ${node.javaClass.simpleName}")
        }
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
            ?: error("missing token source: ${property.symbol()}")
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

private fun targetSymbol(target: JsonObject): String {
    val owner = target["owner"].asString.replace('$', '.')
    val holder = if (!target["dispatchReceiver"].isJsonNull) owner else target["package"].asString
    return if (target["declarationKind"].asString == "constructor") {
        owner
    } else {
        holder + "." + target["name"].asString
    }
}

private fun CallableDescriptor.matches(target: JsonObject, defaults: Boolean = true): Boolean {
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

private fun resolveTarget(
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

private fun readSources(request: JsonObject, factory: KtPsiFactory): List<KtFile> =
    request.getAsJsonArray("sources").flatMap { entry ->
        ZipFile(entry.asJsonObject["file"].asString).use { zip ->
            zip.entries().asSequence().filter {
                it.name.endsWith(".kt") &&
                    !it.name.startsWith("commonStubsMain/") &&
                    !it.name.startsWith("jvmStubsMain/")
            }.map { item ->
                factory.createFile(
                    item.name.substringAfterLast('/'),
                    zip.getInputStream(item).bufferedReader().readText(),
                )
            }.toList()
        }
    }

fun main(args: Array<String>) {
    val gson = GsonBuilder().serializeNulls().disableHtmlEscaping().create()
    val request = gson.fromJson(File(args[0]).readText(), JsonObject::class.java)
    val disposable = Disposer.newDisposable()
    try {
        val config = CompilerConfiguration().apply {
            put(CommonConfigurationKeys.MODULE_NAME, "compose-default-evidence")
            put(CommonConfigurationKeys.MESSAGE_COLLECTOR_KEY, MessageCollector.NONE)
            extensionsStorage = ExtensionStorage()
            addJvmClasspathRoots(request.getAsJsonArray("classpath").map { File(it.asString) })
        }
        val environment = KotlinCoreEnvironment.createForProduction(
            disposable,
            config,
            EnvironmentConfigFiles.JVM_CONFIG_FILES,
        )
        val factory = KtPsiFactory(environment.project, false)
        val files = readSources(request, factory)
        val context = TopDownAnalyzerFacadeForJVM.analyzeFilesWithJavaIntegration(
            environment.project,
            files,
            NoScopeRecordCliBindingTrace(environment.project),
            config,
            environment::createPackagePartProvider,
        ).bindingContext
        val declarations = files.flatMap {
            PsiTreeUtil.collectElementsOfType(it, KtDeclaration::class.java)
        }.mapNotNull { node ->
            (context[BindingContext.DECLARATION_TO_DESCRIPTOR, node] as? CallableDescriptor)
                ?.let { node to it }
        }
        val defaults = Defaults(context)
        val results = request.getAsJsonArray("targets").map { record ->
            resolveTarget(record.asJsonObject, declarations, defaults)
        }
        File(args[1]).writeText(
            gson.toJson(
                mapOf(
                    "formatVersion" to 1,
                    "inventoryHash" to request["inventoryHash"],
                    "toolHash" to request["toolHash"],
                    "sources" to request.getAsJsonArray("sources"),
                    "declarations" to results,
                ),
            ) + "\n",
        )
        println("Resolved defaults for ${results.size} pinned declarations")
    } finally {
        Disposer.dispose(disposable)
    }
}
