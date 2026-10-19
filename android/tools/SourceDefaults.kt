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
import org.jetbrains.kotlin.psi.KtClassOrObject
import org.jetbrains.kotlin.psi.KtDeclaration
import org.jetbrains.kotlin.psi.KtFile
import org.jetbrains.kotlin.psi.KtNamedDeclaration
import org.jetbrains.kotlin.psi.KtPsiFactory
import org.jetbrains.kotlin.resolve.BindingContext
import java.io.File
import java.util.zip.ZipFile

private class SourceIndex(files: List<KtFile>) {
    private val bySymbol = mutableMapOf<String, MutableList<KtFile>>()

    init {
        files.forEach { file ->
            val packageName = file.packageFqName.asString()
            fun record(scope: String, declaration: KtNamedDeclaration) {
                val name = declaration.name ?: return
                val symbol = if (scope.isEmpty()) name else "$scope.$name"
                val key = if (packageName.isEmpty()) symbol else "$packageName.$symbol"
                bySymbol.getOrPut(key) { mutableListOf() }.add(file)
                if (declaration is KtClassOrObject) {
                    declaration.declarations.filterIsInstance<KtNamedDeclaration>()
                        .forEach { record(symbol, it) }
                }
            }
            file.declarations.filterIsInstance<KtNamedDeclaration>().forEach { record("", it) }
        }
    }

    /** Files declaring the symbol itself, or failing that its containing class. */
    fun declaring(symbol: String): List<KtFile> =
        (bySymbol[symbol] ?: bySymbol[symbol.substringBeforeLast('.')]).orEmpty()
}

/**
 * The target-declaring source files, plus an index of every extracted file. Everything
 * else resolves through the classpath from the artifacts' own bytecode, which keeps the
 * analysis clear of source files no pinned target needs. A file name's stem matches its
 * platform variants too (`FontScaling.kt`, `FontScaling.android.kt`), which is where
 * expect declarations keep the defaults their actuals inherit.
 */
private fun readSources(
    request: JsonObject,
    factory: KtPsiFactory,
): Pair<LinkedHashSet<KtFile>, SourceIndex> {
    val stems =
        request.getAsJsonArray("targets")
            .mapNotNull { it.asJsonObject["sourceFile"]?.asString }
            .map { it.substringBefore('.') }
            .toSet()
    val files =
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
    return LinkedHashSet(files.filter { it.name.substringBefore('.') in stems }) to
        SourceIndex(files)
}

/**
 * Evidence for every pinned target, re-analysing whenever a token default turns out to
 * live in a file the first pass did not select. Nothing else widens the set, so the loop
 * ends as soon as no target reads a token it cannot reduce.
 */
private fun resolveTargets(
    request: JsonObject,
    environment: KotlinCoreEnvironment,
    config: CompilerConfiguration,
    files: LinkedHashSet<KtFile>,
    index: SourceIndex,
): List<Map<String, Any?>> {
    var passes = 0
    while (true) {
        passes++
        val context =
            TopDownAnalyzerFacadeForJVM.analyzeFilesWithJavaIntegration(
                environment.project,
                files,
                NoScopeRecordCliBindingTrace(environment.project),
                config,
                environment::createPackagePartProvider,
            ).bindingContext
        val declarations =
            files.flatMap {
                PsiTreeUtil.collectElementsOfType(it, KtDeclaration::class.java)
            }.mapNotNull { node ->
                (context[BindingContext.DECLARATION_TO_DESCRIPTOR, node] as? CallableDescriptor)
                    ?.let { node to it }
            }
        val defaults = Defaults(context)
        val results =
            request.getAsJsonArray("targets").map { record ->
                resolveTarget(record.asJsonObject, declarations, defaults)
            }
        val added = defaults.missing.flatMap { index.declaring(it) }.filter { files.add(it) }
        if (added.isEmpty()) {
            println("Analysed ${files.size} source files; $passes analysis passes")
            return results
        }
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
        val (files, index) = readSources(request, factory)
        val results = resolveTargets(request, environment, config, files, index)
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
