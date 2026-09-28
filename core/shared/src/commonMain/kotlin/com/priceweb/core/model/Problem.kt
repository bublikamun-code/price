package com.priceweb.core.model

import kotlinx.serialization.Serializable

/** RFC 9457 problem+json, как его отдаёт бэкенд (apps/api/app/schemas/v2/common.py). */
@Serializable
data class ProblemDetails(
    val type: String? = null,
    val title: String? = null,
    val status: Int? = null,
    val detail: String? = null,
    val instance: String? = null,
    val code: String? = null,
    val requestId: String? = null,
    val errors: List<ProblemFieldError> = emptyList(),
)

@Serializable
data class ProblemFieldError(
    val field: String? = null,
    val code: String? = null,
    val message: String? = null,
)
