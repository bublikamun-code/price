package com.priceweb.core.model

import kotlinx.serialization.Serializable

/**
 * Денежная сумма. [amount] остаётся строкой: на проводе контракт требует
 * фиксированные два знака, и любое промежуточное сложение в Double здесь
 * рано или поздно даст 99.99999999. Форматирование — забота слоя представления.
 */
@Serializable
data class Money(
    val amount: String,
    val currency: String,
)

/** Курс валюты: строковое значение с четырьмя знаками, [scale] — число знаков. */
@Serializable
data class Rate(
    val value: String,
    val scale: Int,
    val source: String,
)

/**
 * Стабильный медиа-ресурс (§16 п.37).
 *
 * [id] пригоден как ключ кэша и не меняется между выдачами; [url] ведёт на
 * v2-эндпоинт, который отдаёт байты изображения (200) без редиректа на внешний
 * S3: редирект на http-хост резался бы на https-клиенте как mixed content.
 */
@Serializable
data class MediaResource(
    val id: String,
    val url: String,
    val width: Int,
    val height: Int,
    val mimeType: String,
)

@Serializable
data class ResponseMeta(
    val requestId: String,
)

@Serializable
data class CursorMeta(
    val requestId: String,
    val nextCursor: String? = null,
    val hasMore: Boolean = false,
    val limit: Int,
    val sort: String,
)

@Serializable
data class SuccessResponse<T>(
    val data: T,
    val meta: ResponseMeta,
)

@Serializable
data class CursorResponse<T>(
    val data: List<T>,
    val meta: CursorMeta,
)
