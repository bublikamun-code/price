// Корневой build-файл нативных клиентов.
//
// Плагины объявлены, но не применены: Android-модуль включается только когда
// установлен Android SDK (см. shared/build.gradle.kts и флаг enableAndroid).
//
// Версия Kotlin держится в одном месте, потому что Kotlin/Native линкуется с тем
// toolchain, который отдаёт Xcode: старая KGP не умеет работать с новым SDK
// вообще. Под Xcode 27 рабочей оказалась 2.4.20.
plugins {
    id("com.android.library") version "8.7.3" apply false
    id("org.jetbrains.kotlin.multiplatform") version "2.4.20" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "2.4.20" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.20" apply false
}
