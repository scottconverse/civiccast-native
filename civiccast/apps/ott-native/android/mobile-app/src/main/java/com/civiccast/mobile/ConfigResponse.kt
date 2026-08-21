package com.civiccast.mobile

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Real CivicCast app-platform contract (`civiccast/app_platform/models.py`).
 * `GET <API_BASE_URL>/api/public/app/config` returns [ConfigResponse]; each
 * channel's `liveStateUrl` is fetched separately (it is a path relative to
 * the API host, not an absolute URL) to resolve [LiveState.playbackUrl] —
 * the HLS manifest to play.
 */
@Serializable
data class ConfigResponse(
    val stationName: String,
    val defaultChannelId: String,
    val channels: List<Channel> = emptyList()
) {
    /** Mirrors `selectDefaultChannel()` in app-platform-shells/src/shell.mjs. */
    fun defaultChannel(): Channel? =
        channels.firstOrNull { it.id == defaultChannelId } ?: channels.firstOrNull()
}

@Serializable
data class ChannelBranding(
    val displayName: String,
    val shortName: String? = null,
    val color: String? = null,
    val logoText: String? = null,
    val logoUrl: String? = null
)

@Serializable
data class Channel(
    @SerialName("channel_id") val id: String,
    val branding: ChannelBranding,
    val liveStateUrl: String
)

@Serializable
data class LiveState(
    val state: String,
    val playbackUrl: String? = null,
    val title: String? = null,
    val fallbackReason: String? = null
) {
    val summary: String
        get() {
            val label = if (state == "fallback") (fallbackReason ?: "fallback") else (title ?: playbackUrl ?: "no active program")
            return "$state: $label"
        }
}
