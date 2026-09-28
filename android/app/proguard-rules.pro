# KMP-ядро и Ktor собираются с обфускацией имён классов, поэтому правила
# держатся на контракте, а не на конкретных именах: имена при сериализации
# DTO идут по аннотациям @SerialName и потому устойчивы.
-keepclassmembers class kotlinx.serialization.json.** { *; }
-keep,includedescriptorclasses class com.priceweb.core.**$$serializer { *; }
-keepclassmembers class com.priceweb.core.** {
    *** Companion;
}
-keepclasseswithmembers class com.priceweb.core.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# Ktor и OkHttp тянут рефлексию по параметрам движка; без правил R8 оставит
# только точки входа, и клиент упадёт на первом же запросе.
-keep class io.ktor.client.engine.okhttp.** { *; }
-dontwarn org.slf4j.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
