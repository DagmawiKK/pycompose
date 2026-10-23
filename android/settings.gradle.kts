pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "PyCompose"
include(":ir", ":renderer", ":host")

// Development-only Compose API extraction (plan 31 S1). A scaffolded app is handed
// generated code and has no such module, so it is included only where it exists.
if (file("compose-extract").isDirectory) include(":compose-extract")
