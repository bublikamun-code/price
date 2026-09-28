package com.priceweb.core.session

import com.priceweb.core.CoreJson
import com.priceweb.core.model.SessionGrant
import kotlinx.cinterop.CPointer
import kotlinx.cinterop.CPointerVarOf
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.MemScope
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.alloc
import kotlinx.cinterop.interpretObjCPointer
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.objcPtr
import kotlinx.cinterop.ptr
import kotlinx.cinterop.usePinned
import kotlinx.cinterop.value
import platform.CoreFoundation.CFDictionaryCreateMutable
import platform.CoreFoundation.CFDictionaryRef
import platform.CoreFoundation.CFDictionarySetValue
import platform.CoreFoundation.CFRelease
import platform.CoreFoundation.CFStringCreateWithCString
import platform.CoreFoundation.CFStringRef
import platform.CoreFoundation.CFTypeRefVar
import platform.CoreFoundation.kCFAllocatorDefault
import platform.CoreFoundation.kCFBooleanTrue
import platform.CoreFoundation.kCFStringEncodingUTF8
import platform.Foundation.NSData
import platform.Foundation.dataWithBytes
import platform.Foundation.getBytes
import platform.Security.SecItemAdd
import platform.Security.SecItemCopyMatching
import platform.Security.SecItemDelete
import platform.Security.errSecSuccess
import platform.Security.kSecAttrAccessible
import platform.Security.kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
import platform.Security.kSecAttrAccount
import platform.Security.kSecAttrService
import platform.Security.kSecClass
import platform.Security.kSecClassGenericPassword
import platform.Security.kSecReturnData
import platform.Security.kSecValueData

/**
 * Хранилище токенов на iOS: Keychain, класс `kSecClassGenericPassword`.
 *
 * Refresh-токен — секрет уровня сессии: он живёт неделю и позволяет получить
 * новый access без пароля. `UserDefaults` здесь не годится (файл читается
 * бэкапом), а `NSUserDefaults` тем более.
 *
 * Запись одна на всё приложение, с `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`:
 * токен не должен ни попасть в бэкап iCloud, ни пережить сброс устройства.
 */
@OptIn(ExperimentalForeignApi::class)
actual class TokenStore(
    private val service: String = "com.priceweb.core.session",
    private val account: String = "refresh",
) {
    actual suspend fun load(): SessionGrant? {
        val data: NSData? = keychainQuery(
            extras = { set(kSecReturnData, kCFBooleanTrue) },
        ) { query ->
            val result = alloc<CFTypeRefVar>()
            if (SecItemCopyMatching(query, result.ptr) != errSecSuccess) {
                return@keychainQuery null
            }
            // Ответ — CFData, и тип гарантирует уже OSStatus выше. Приводить
            // его надо указателем на объект: в системе типов Kotlin `NSData`
            // и `CFTypeRef` не связаны родством, поэтому `as?` здесь только
            // помечается предупреждением «cast can never succeed» и ничего
            // не проверяет.
            result.value?.let { interpretObjCPointer<NSData>(it.objcPtr()) }
        }
        if (data == null) return null

        val length = data.length.toInt()
        if (length <= 0) return null

        val buffer = ByteArray(length)
        buffer.usePinned { pinned ->
            data.getBytes(pinned.addressOf(0), length.toULong())
        }
        return runCatching {
            CoreJson.instance.decodeFromString<SessionGrant>(buffer.decodeToString())
        }.getOrNull()
    }

    actual suspend fun save(grant: SessionGrant) {
        val payload = CoreJson.instance.encodeToString(grant).encodeToByteArray()
        val data = payload.usePinned { pinned ->
            NSData.dataWithBytes(pinned.addressOf(0), payload.size.toULong())
        }
        keychainQuery(
            extras = {
                setData(kSecValueData, data)
                set(kSecAttrAccessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly)
            },
        ) { query ->
            // Сначала удаляем возможную старую запись: refresh продлевает grant
            // и пишет повторно, а SecItemAdd на существующем элементе вернёт
            // errSecDuplicateItem, и новый токен молча не сохранится.
            SecItemDelete(query)
            SecItemAdd(query, null)
        }
    }

    actual suspend fun clear() {
        keychainQuery { query -> SecItemDelete(query) }
    }

    private fun <R> keychainQuery(
        extras: QueryBuilder.() -> Unit = {},
        block: MemScope.(CFDictionaryRef) -> R,
    ): R = memScoped {
        val builder = QueryBuilder()
        try {
            // Идентификатор записи — всегда kSecClassGenericPassword, а service
            // и account — единственные значения, которые приходят извне.
            builder.set(kSecClass, kSecClassGenericPassword)
            builder.setString(kSecAttrService, service)
            builder.setString(kSecAttrAccount, account)
            builder.extras()
            block(builder.dictionary)
        } finally {
            builder.close()
        }
    }

    /**
     * Словарь запроса Keychain, который сам следит за своими объектами.
     *
     * Собирать запрос из C-строк нельзя: Security обходит его, кодируя для
     * отправки в `securityd`, и берёт каждое значение за объект CoreFoundation.
     * По C-строке он читает мусор вместо `isa` и падает с `EXC_BAD_ACCESS`
     * внутри `der_sizeof_plist` — на самом первом чтении токена, сразу при
     * старте приложения. Поэтому ключи и константы берутся прямо из
     * `platform.Security` (там они настоящие `CFStringRef`), а строки из
     * Kotlin создаются как `CFString`.
     */
    private class QueryBuilder {
        val dictionary: CFDictionaryRef =
            requireNotNull(CFDictionaryCreateMutable(null, 8, null, null)) {
                "Keychain не дал создать словарь запроса"
            }

        /**
         * Строки, отданные в словарь: на каждую своя ссылка, и она живёт до
         * конца вызова Security.
         *
         * Освобождать их сразу после вставки нельзя — обход запроса должен
         * увидеть все объекты живыми, иначе `SecItemCopyMatching` падает с
         * `EXC_BAD_ACCESS` уже на своей копии словаря.
         */
        private val owned = mutableListOf<CFStringRef?>()

        fun set(key: CFStringRef?, value: CPointer<*>?) {
            CFDictionarySetValue(dictionary, key, value)
        }

        fun setString(key: CFStringRef?, value: String) {
            val string = requireNotNull(
                CFStringCreateWithCString(kCFAllocatorDefault, value, kCFStringEncodingUTF8),
            ) { "Keychain не дал создать строку запроса" }
            CFDictionarySetValue(dictionary, key, string)
            owned += string
        }

        /**
         * `NSData` в словаре Keychain должен лежать как `CFTypeRef`, а не как
         * объект Objective-C: оборачиваем указатель на него в `CPointerVarOf`.
         */
        fun setData(key: CFStringRef?, value: NSData) {
            memScoped {
                val slot = alloc<CPointerVarOf<CPointer<*>>>()
                slot.value = interpretObjCPointer<CPointer<*>>(value.objcPtr())
                CFDictionarySetValue(dictionary, key, slot.ptr)
            }
        }

        fun close() {
            // Сначала словарь: он снимает свои ссылки, и только потом мы
            // снимаем свои. В обратном порядке строка освободилась бы раньше,
            // чем её отпустит словарь.
            CFRelease(dictionary)
            owned.forEach { CFRelease(it) }
        }
    }
}
