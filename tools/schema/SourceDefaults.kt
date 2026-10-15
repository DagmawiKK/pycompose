// Development-only compiler frontend. Emit data, never source-expression strings.
import com.google.gson.GsonBuilder
import com.google.gson.JsonObject
import org.jetbrains.kotlin.cli.common.messages.MessageCollector
import org.jetbrains.kotlin.cli.jvm.compiler.EnvironmentConfigFiles
import org.jetbrains.kotlin.cli.jvm.compiler.KotlinCoreEnvironment
import org.jetbrains.kotlin.cli.jvm.compiler.NoScopeRecordCliBindingTrace
import org.jetbrains.kotlin.cli.jvm.compiler.TopDownAnalyzerFacadeForJVM
import org.jetbrains.kotlin.cli.jvm.config.addJvmClasspathRoots
import org.jetbrains.kotlin.com.intellij.openapi.util.Disposer
import org.jetbrains.kotlin.com.intellij.psi.util.PsiTreeUtil
import org.jetbrains.kotlin.config.CommonConfigurationKeys
import org.jetbrains.kotlin.config.CompilerConfiguration
import org.jetbrains.kotlin.descriptors.CallableDescriptor
import org.jetbrains.kotlin.descriptors.ConstructorDescriptor
import org.jetbrains.kotlin.descriptors.DeclarationDescriptor
import org.jetbrains.kotlin.descriptors.DeclarationDescriptorWithVisibility
import org.jetbrains.kotlin.descriptors.DescriptorVisibilities
import org.jetbrains.kotlin.descriptors.PropertyDescriptor
import org.jetbrains.kotlin.psi.*
import org.jetbrains.kotlin.resolve.BindingContext
import org.jetbrains.kotlin.resolve.DescriptorToSourceUtils
import org.jetbrains.kotlin.resolve.DescriptorUtils
import org.jetbrains.kotlin.resolve.calls.util.getResolvedCall
import org.jetbrains.kotlin.types.KotlinType
import java.io.File
import java.util.zip.ZipFile

private fun DeclarationDescriptor.symbol(): String = DescriptorUtils.getFqNameSafe(this).asString()

private fun KotlinType.classifier(): String = constructor.declarationDescriptor!!.symbol().replace('.', '/')

private fun KotlinType.matches(type: JsonObject): Boolean =
    classifier() == type["classifier"].asString &&
        isMarkedNullable == type["nullable"].asBoolean &&
        arguments.size == type.getAsJsonArray("arguments").size() &&
        arguments.zip(type.getAsJsonArray("arguments")).all { (actual, expected) ->
            !actual.isStarProjection && !expected.asJsonObject["type"].isJsonNull &&
                actual.type.matches(expected.asJsonObject.getAsJsonObject("type"))
        }

/**
 * A reference default is only reusable when the symbol really is the declared
 * type. Anything looser risks generating Kotlin that does not type-check.
 */
private fun KotlinType.sameAs(other: KotlinType): Boolean =
    classifier() == other.classifier() &&
        isMarkedNullable == other.isMarkedNullable &&
        arguments.size == other.arguments.size &&
        arguments.zip(other.arguments).all { (a, b) ->
            a.projectionKind == b.projectionKind && a.type?.sameAs(b.type) == true
        }

private fun DeclarationDescriptor.exported(): Boolean =
    (this !is DeclarationDescriptorWithVisibility || visibility == DescriptorVisibilities.PUBLIC) &&
        (containingDeclaration?.let { it !is org.jetbrains.kotlin.descriptors.PackageFragmentDescriptor && !it.exported() } != true)

private class Defaults(private val context: BindingContext) {
    fun expression(node: KtExpression): Map<String, Any?> {
        check(context.diagnostics.all().none {
            it.severity == org.jetbrains.kotlin.diagnostics.Severity.ERROR &&
                it.psiElement.containingFile == node.containingFile &&
                node.textRange.contains(it.psiElement.textRange)
        }) { "compiler error in default expression" }
        val type = context.getType(node) ?: error("unresolved default type")
        if (node is KtParenthesizedExpression) return expression(node.expression!!)
        if (node is KtConstantExpression || node is KtPrefixExpression) {
            val value = context[BindingContext.COMPILE_TIME_VALUE, node]
                ?.takeUnless { it.isError }?.getValue(type)
            check(value == null || value is Number || value is Boolean) { "unsupported literal" }
            check(value != null || node.text == "null") { "unresolved literal" }
            return mapOf("kind" to "literal", "type" to type.classifier(), "value" to value)
        }
        val reference = when (node) {
            is KtNameReferenceExpression -> node
            is KtDotQualifiedExpression -> node.selectorExpression as? KtNameReferenceExpression
            else -> null
        }
        if (reference != null) {
            val property = context[BindingContext.REFERENCE_TARGET, reference] as? PropertyDescriptor
                ?: error("default is not a resolved property")
            check(!property.isVar) { "mutable default reference" }
            check(property.exported()) {
                "non-public default ${property.symbol()}"
            }
            // A property reference is only safe when it really is the value the
            // parameter declares; anything else is a protocol, not a default.
            check(property.type.sameAs(type)) {                "default ${property.symbol()} is not a ${type.classifier()}"
            }
            val symbol = property.symbol()
            if (property.extensionReceiverParameter != null) {
                val receiver = (node as? KtDotQualifiedExpression)?.receiverExpression
                    ?: error("implicit extension receiver in default")
                return mapOf("kind" to "extensionProperty", "symbol" to symbol, "receiver" to expression(receiver))
            }
            check(property.dispatchReceiverParameter == null ||
                (property.containingDeclaration as? org.jetbrains.kotlin.descriptors.ClassDescriptor)?.kind ==
                org.jetbrains.kotlin.descriptors.ClassKind.OBJECT) { "instance property default: $symbol" }
            return mapOf("kind" to "property", "symbol" to symbol)
        }
        val call = (node as? KtCallExpression) ?: (node as? KtDotQualifiedExpression)?.selectorExpression as? KtCallExpression
        if (call != null) {
            val resolved = call.getResolvedCall(context) ?: error("unresolved default call")
            check(resolved.status.isSuccess) { "ambiguous/invalid default call" }
            val target = resolved.resultingDescriptor
            check(target.exported() && target.extensionReceiverParameter == null) { "non-public/extension default call" }
            check(target is ConstructorDescriptor || target.dispatchReceiverParameter == null ||
                (target.containingDeclaration as? org.jetbrains.kotlin.descriptors.ClassDescriptor)?.kind ==
                org.jetbrains.kotlin.descriptors.ClassKind.OBJECT) { "instance default call" }
            // Only a zero-argument call is a reusable policy. Anything with
            // arguments would smuggle per-binding Kotlin back into the schema.
            check(resolved.valueArguments.isEmpty()) { "default call takes arguments" }
            return mapOf("kind" to "call", "symbol" to
                (if (target is ConstructorDescriptor) target.containingDeclaration.symbol() else target.symbol()))
        }
        error("unsupported default syntax: ${node.javaClass.simpleName}")
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
            addJvmClasspathRoots(request.getAsJsonArray("classpath").map { File(it.asString) })
        }
        val environment = KotlinCoreEnvironment.createForProduction(disposable, config, EnvironmentConfigFiles.JVM_CONFIG_FILES)
        val factory = KtPsiFactory(environment.project, false)
        val files = request.getAsJsonArray("sources").flatMap { entry ->
            val source = entry.asJsonObject
            ZipFile(source["file"].asString).use { zip ->
                zip.entries().asSequence().filter {
                    it.name.endsWith(".kt") && !it.name.startsWith("commonStubsMain/") &&
                        !it.name.startsWith("jvmStubsMain/")
                }.map { item ->
                    factory.createFile(item.name.substringAfterLast('/'), zip.getInputStream(item).bufferedReader().readText())
                }.toList()
            }
        }
        val context = TopDownAnalyzerFacadeForJVM.analyzeFilesWithJavaIntegration(
            environment.project, files, NoScopeRecordCliBindingTrace(environment.project), config, environment::createPackagePartProvider,
        ).bindingContext
        val declarations = files.flatMap { PsiTreeUtil.collectElementsOfType(it, KtDeclaration::class.java) }
            .mapNotNull { node -> (context[BindingContext.DECLARATION_TO_DESCRIPTOR, node] as? CallableDescriptor)?.let { node to it } }
        val defaults = Defaults(context)
        val results = request.getAsJsonArray("targets").map { record ->
            val target = record.asJsonObject
            val parameters = target.getAsJsonArray("parameters")
            val kind = target["declarationKind"].asString
            val symbol = if (kind == "constructor") target["owner"].asString.replace('$', '.') else
                (if (!target["dispatchReceiver"].isJsonNull) target["owner"].asString.replace('$', '.') else target["package"].asString) + "." + target["name"].asString
            val matches = declarations.filter { (node, descriptor) ->
                val identity = if (descriptor is ConstructorDescriptor) descriptor.containingDeclaration.symbol() else descriptor.symbol()
                identity == symbol && (descriptor is ConstructorDescriptor) == (kind == "constructor") &&
                    descriptor.valueParameters.size == parameters.size() &&
                    descriptor.valueParameters.zip(parameters).all { (actual, expected) ->
                        actual.name.asString() == expected.asJsonObject["name"].asString &&
                            actual.type.matches(expected.asJsonObject.getAsJsonObject("type")) &&
                            actual.declaresDefaultValue() == expected.asJsonObject["hasDefault"].asBoolean
                    } && descriptor.returnType?.matches(target.getAsJsonObject("returnType")) == true &&
                    (target["sourceFile"].isJsonNull || node.containingKtFile.name == target["sourceFile"].asString)
            }
            val expressions = parameters.filter { it.asJsonObject["hasDefault"].asBoolean }.associate { parameter ->
                val name = parameter.asJsonObject["name"].asString
                val expression = runCatching {
                    check(matches.size == 1) { "source/signature disagreement: ${matches.size} matches for $symbol" }
                    val descriptor = matches.single().second.valueParameters.single { it.name.asString() == name }
                    val psi = DescriptorToSourceUtils.descriptorToDeclaration(descriptor) as? KtParameter
                    defaults.expression(psi?.defaultValue ?: error("missing source default"))
                }.getOrElse { mapOf("kind" to "unsupported", "reason" to (it.message ?: it.javaClass.simpleName)) }
                name to expression
            }
            mapOf("owner" to target["owner"].asString, "jvm" to target["jvm"],
                "matched" to (matches.size == 1), "defaults" to expressions)
        }
        File(args[1]).writeText(gson.toJson(mapOf(
            "formatVersion" to 1, "inventoryHash" to request["inventoryHash"],
            "toolHash" to request["toolHash"],
            "sources" to request.getAsJsonArray("sources"),
            "declarations" to results,
        )) + "\n")
        println("Resolved defaults for ${results.size} pinned declarations")
    } finally {
        Disposer.dispose(disposable)
    }
}
