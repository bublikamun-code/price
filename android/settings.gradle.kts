pluginManagement {
    repositories {
        gradlePluginPortal()
        google()
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "price-web-android"

// Общее Kotlin-ядро живёт в core/ и проверяется отдельно (`make mobile-test`).
// Здесь оно подключается как подпроект, а не как готовый артефакт: иначе
// каждый чих в контракте требовал бы пересборки и перепубликации ядра перед
// сборкой приложения.
include(":app")
include(":shared")
project(":shared").projectDir = file("../core/shared")
