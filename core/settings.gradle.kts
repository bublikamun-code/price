// Gradle-корень нативных клиентов.
//
// Лежит отдельным деревом от корня репозитория: там Docker/Nuxt, и общий
// settings.gradle на весь монорепозиторий смешал бы два несвязанных мира.
pluginManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
        google()
    }
}

dependencyResolutionManagement {
    repositories {
        mavenCentral()
        google()
    }
}

rootProject.name = "price-web-core"

include(":shared")
