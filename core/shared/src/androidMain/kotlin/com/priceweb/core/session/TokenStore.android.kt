package com.priceweb.core.session

import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.priceweb.core.CoreJson
import com.priceweb.core.model.SessionGrant

/**
 * Хранилище токенов на Android — `EncryptedSharedPreferences`.
 *
 * Значения и имена ключей шифруются ключом из Android Keystore: прочитать
 * файл настроек без доступа к устройству нельзя. Refresh-токен живёт семь дней
 * и по сути равен паролю, поэтому держать его в обычных `SharedPreferences` —
 * значит отдать его тому, кто вытащил данные приложения через root или бэкап.
 *
 * Формат хранения совпадает с iOS: весь grant одной JSON-строкой. Два
 * независимых разбора на двух платформах — это два места, где они
 * разъедутся, а симметричный формат исключает такую возможность.
 */
actual class TokenStore {

    private val preferences: SharedPreferences by lazy { encryptedPreferences() }

    private fun encryptedPreferences(): SharedPreferences {
        val context = PriceWebPlatform.requireContext()
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            context,
            FILE_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    actual suspend fun load(): SessionGrant? {
        val json = preferences.getString(KEY_GRANT, null) ?: return null
        // Запись может остаться от прошлой версии приложения или побиться при
        // прерывании записи. Нечитаемый grant — это «сессии нет», а не падение:
        // иначе приложение до бесконечности получало бы 401 по мусорному токену.
        return runCatching { CoreJson.instance.decodeFromString<SessionGrant>(json) }.getOrNull()
    }

    actual suspend fun save(grant: SessionGrant) {
        preferences.edit()
            .putString(KEY_GRANT, CoreJson.instance.encodeToString(grant))
            .apply()
    }

    actual suspend fun clear() {
        preferences.edit().clear().apply()
    }

    private companion object {
        const val FILE_NAME = "priceweb.session"
        const val KEY_GRANT = "grant"
    }
}
