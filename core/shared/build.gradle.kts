import org.jetbrains.kotlin.gradle.ExperimentalKotlinGradlePluginApi
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("org.jetbrains.kotlin.multiplatform")
    id("org.jetbrains.kotlin.plugin.serialization")
}

// Нативные таргеты включаются флагами, а не всегда: iOS требует Xcode
// (Kotlin/Native тянет Apple SDK оттуда), Android — Android SDK. Без них
// `./gradlew :shared:jvmTest` собирает и проверяет ровно то же общее ядро,
// просто без платформенных actual'ов. См. README.md раздела core/.
val enableIos = providers.gradleProperty("enableIos").orNull == "true"
val enableAndroid = providers.gradleProperty("enableAndroid").orNull == "true"

kotlin {
    jvmToolchain(21)

    jvm()

    if (enableAndroid) {
        androidTarget {
            @OptIn(ExperimentalKotlinGradlePluginApi::class)
            compilerOptions {
                jvmTarget.set(JvmTarget.JVM_17)
            }
        }
    }

    if (enableIos) {
        listOf(iosX64(), iosArm64(), iosSimulatorArm64()).forEach { target ->
            // Без этого блока задачи linkDebugFrameworkIos* не существует,
            // и Swift-приложению не с чем импортировать. Xcode ищет результат
            // по FRAMEWORK_SEARCH_PATHS, поэтому имя должно быть ровно таким.
            target.binaries.framework {
                baseName = "shared"
                isStatic = true
            }
        }
    }

    // Шаблон иерархии применяем здесь, а не в его автоматический момент ближе
    // к концу конфигурации: промежуточный sourceSet `iosMain` нужен уже в
    // блоке `sourceSets` ниже, и без раннего вызова он не создан.
    applyDefaultHierarchyTemplate()

    sourceSets {
        commonMain.dependencies {
            implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.1")
            implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.0")
            implementation("org.jetbrains.kotlinx:kotlinx-datetime:0.6.2")
            implementation("io.ktor:ktor-client-core:3.1.1")
            implementation("io.ktor:ktor-client-content-negotiation:3.1.1")
            implementation("io.ktor:ktor-serialization-kotlinx-json:3.1.1")
        }
        commonTest.dependencies {
            implementation(kotlin("test"))
        }
        jvmMain.dependencies {
            implementation("io.ktor:ktor-client-cio:3.1.1")
        }
        if (enableIos) {
            iosMain.dependencies {
                // URLSession: см. KDoc в PlatformHttpClient.ios.kt.
                implementation("io.ktor:ktor-client-darwin:3.1.1")
            }
        }
        jvmTest.dependencies {
            implementation("io.ktor:ktor-client-mock:3.1.1")
            implementation("io.ktor:ktor-client-cio:3.1.1")
            implementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.1")
        }
    }
}

// Android-модуль включается только вместе с флагом `enableAndroid`: применение
// com.android.library требует установленного SDK, и без него даже конфигурация
// Gradle падает. Плагин применяется императивным apply(), а не в блоке
// `plugins` — тот hoist'ится и выполнился бы раньше проверки флага.
if (enableAndroid) {
    apply(plugin = "com.android.library")

    extensions.configure<com.android.build.gradle.LibraryExtension>("android") {
        namespace = "com.priceweb.core"
        compileSdk = 35
        defaultConfig {
            minSdk = 26
        }
        compileOptions {
            sourceCompatibility = JavaVersion.VERSION_17
            targetCompatibility = JavaVersion.VERSION_17
        }
    }

    // Зависимости androidMain объявляются здесь, а не в блоке `sourceSets`
    // выше: без Android SDK Gradle не знает, что это за набор исходников,
    // и падает на самом обращении к нему.
    kotlin.sourceSets.getByName("androidMain").dependencies {
        implementation("androidx.security:security-crypto:1.1.0-alpha06")
        implementation("io.ktor:ktor-client-okhttp:3.1.1")
    }
}
