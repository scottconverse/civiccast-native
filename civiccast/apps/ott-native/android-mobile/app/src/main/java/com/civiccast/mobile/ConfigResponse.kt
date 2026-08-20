package com.civiccast.mobile

import kotlinx.serialization.Serializable

/**
 * Response shape for GET /api/public/app/config.
 *
 * Kept intentionally small — the starter only needs station identity + a flat list of live channels.
 * Add EPG / VOD / categories here as the backend grows.
 */
@Serializable
data class ConfigResponse(
    val station: Station,
    val channels: List<Channel> = emptyList()
)

@Serializable
data class Station(
    val name: String,
    val logoUrl: String? = null
)

@Serializable
data class Channel(
    val id: String,
    val name: String,
    val hlsUrl: String,
    val posterUrl: String? = null,
    val description: String? = null
)
