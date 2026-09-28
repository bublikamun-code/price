package com.priceweb.core.model

import kotlinx.datetime.Instant
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Текущий пользователь в v2-проекции (apps/api/app/schemas/v2/session.py). */
@Serializable
data class CurrentUser(
    val id: String,
    val email: String,
    val fullName: String,
    val role: String,
    val isActive: Boolean,
    val displayCurrency: String,
    val consentAccepted: Boolean,
    val totpEnabled: Boolean,
    val priceDigestEnabled: Boolean,
    val priceDigestSources: List<String> = emptyList(),
    val forcePasswordChange: Boolean = false,
    val phone: String? = null,
    val legacyCompany: String? = null,
)

/** POST /api/v2/auth/sessions. */
@Serializable
data class NativeLoginRequest(
    val email: String,
    val password: String,
    val clientType: String = "NATIVE",
    val deviceName: String? = null,
    @SerialName("os") val osName: String? = null,
    val appVersion: String? = null,
)

/** POST /api/v2/auth/sessions/refresh. */
@Serializable
data class SessionRefreshRequest(
    val refreshToken: String,
)

/**
 * POST /api/v2/auth/2fa/challenges/verify.
 *
 * Метаданные устройства едут в том же теле, что и ticket+code: сессия рождается
 * именно на этом шаге (§16 п.36).
 */
@Serializable
data class TwoFaVerifyRequest(
    val ticket: String,
    val code: String,
    val clientType: String = "NATIVE",
    val deviceName: String? = null,
    @SerialName("os") val osName: String? = null,
    val appVersion: String? = null,
)

/** Ответ на login при включённой 2FA: токенов нет до verify. */
@Serializable
data class TwoFaChallenge(
    val twoFaRequired: Boolean = true,
    val ticket: String,
    val forcePasswordChange: Boolean = false,
)

/** Запись журнала сессий. */
@Serializable
data class SessionSummary(
    val id: String,
    val createdAt: Instant,
    val expiresAt: Instant,
    val deviceName: String? = null,
    @SerialName("os") val osName: String? = null,
    val appVersion: String? = null,
    val clientType: String? = null,
    val current: Boolean = false,
)

/** Ответ на login/refresh: оба токена в теле, плюс созданная сессия и профиль. */
@Serializable
data class SessionGrant(
    val accessToken: String,
    val accessTokenExpiresAt: Instant,
    val refreshToken: String,
    val refreshTokenExpiresAt: Instant,
    val forcePasswordChange: Boolean = false,
    val session: SessionSummary,
    val user: CurrentUser,
)

/** GET /api/v2/session. */
@Serializable
data class SessionSnapshot(
    val user: CurrentUser,
    val commercialScope: String,
    val organizationId: String? = null,
    val memberships: List<SessionMembership> = emptyList(),
)

@Serializable
data class SessionMembership(
    val organizationId: String,
    val role: String,
)

/** Результат попытки входа: либо токены, либо 2FA-челлендж. */
sealed interface LoginOutcome {
    data class Granted(val grant: SessionGrant) : LoginOutcome
    data class TwoFaRequired(val challenge: TwoFaChallenge) : LoginOutcome
}
