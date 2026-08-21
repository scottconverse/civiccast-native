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

rootProject.name = "CivicCastAndroid"

// S12 de-duplication: android-tv/ and fire-tv/ used to be two entire copied Gradle projects
// (own wrapper, own settings.gradle.kts, near-identical Kotlin source). They are now the single
// :tv-app module below, built as the "tv" and "firetv" product flavors. android-mobile/ becomes
// :mobile-app. One root project, one gradle wrapper, three real app variants.
include(":tv-app")
include(":mobile-app")
