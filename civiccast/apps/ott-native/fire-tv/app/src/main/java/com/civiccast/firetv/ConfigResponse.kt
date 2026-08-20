package com.civiccast.firetv

import kotlinx.serialization.Serializable

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
