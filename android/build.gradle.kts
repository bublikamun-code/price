// Версия Kotlin обязана совпадать с core/build.gradle.kts: модуль `:shared`
// подключается отсюда как подпроект (см. settings.gradle.kts), и две разные KGP
// в одной сборке означают, что метаданные общего ядра просто не прочитаются.
plugins {
    id("com.android.application") version "8.7.3" apply false
    id("com.android.library") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.4.20" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.20" apply false
}
