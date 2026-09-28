plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "by.priceweb.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "by.priceweb.app"
        // 26 — первый уровень с Android Keystore, который умеет
        // AES256_GCM для EncryptedSharedPreferences. Ниже refresh-токен
        // пришлось бы хранить в открытом виде.
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    buildTypes {
        debug {
            // Адрес стенда задаётся сборкой, а не хардкодом: в release тот же
            // код обязан ходить на прод, и забытый literal здесь означал бы
            // отправку персональных цен на localhost с телефона клиента.
            buildConfigField(
                "String",
                "API_BASE_URL",
                "\"${project.findProperty("priceweb.apiBaseUrl") ?: "http://10.0.2.2:8080"}\"",
            )
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            buildConfigField(
                "String",
                "API_BASE_URL",
                "\"${project.findProperty("priceweb.apiBaseUrl") ?: ""}\"",
            )
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(project(":shared"))

    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.navigation:navigation-compose:2.8.5")

    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    debugImplementation("androidx.compose.ui:ui-tooling")

    // OkHttp вместо CIO: на Android он уважает сетевые настройки системы,
    // переиспользует соединение и переживает прокси — всё это нужно мобильному
    // клиенту, который ходит по мобильному интернету.
    implementation("io.ktor:ktor-client-okhttp:3.1.1")

    // Приходит транзитивно и из Ktor, и из Coil, но приложение называет
    // `okhttp3.Interceptor` своими словами: interceptor вешает `Authorization`
    // на запросы Coil к закрытому `/api/v2/media/{id}`. Версия — та же, что у
    // Ktor 3.1.1, чтобы Gradle не разрешил конфликт в рантайме.
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    implementation("io.coil-kt:coil-compose:2.7.0")
}
