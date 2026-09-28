package com.priceweb.core.session

import com.priceweb.core.model.SessionGrant

/**
 * JVM-заглушка хранилища токенов.
 *
 * Существует ради одной причины: чтобы `jvmTest` мог собрать общее ядро и
 * проверить его на общих фикстурах в среде без Xcode и Android SDK. Нативные
 * таргеты используют собственные actual'ы — Keychain на iOS,
 * EncryptedSharedPreferences на Android; этот файл к ним отношения не имеет
 * и в релизные сборки мобильных приложений не попадает.
 *
 * Держит grant в памяти процесса: намеренно без шифрования и без записи на
 * диск, чтобы его нельзя было спутать с боевым хранилищем.
 */
actual class TokenStore {
    private var cached: SessionGrant? = null

    actual suspend fun load(): SessionGrant? = cached

    actual suspend fun save(grant: SessionGrant) {
        cached = grant
    }

    actual suspend fun clear() {
        cached = null
    }
}
