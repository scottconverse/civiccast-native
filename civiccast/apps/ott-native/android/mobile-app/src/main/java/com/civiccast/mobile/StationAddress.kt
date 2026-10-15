package com.civiccast.mobile

import android.content.Context
import android.net.Uri

/** Station selection shared by browsing, artwork and playback. */
object StationAddress {
    @Volatile var baseUrl: String = BuildConfig.API_BASE_URL
        private set

    fun load(context: Context) {
        baseUrl = context.getSharedPreferences("CivicCast", Context.MODE_PRIVATE)
            .getString("stationAddress", BuildConfig.API_BASE_URL) ?: BuildConfig.API_BASE_URL
    }

    fun save(context: Context, address: String): Boolean {
        val value = address.trim().trimEnd('/')
        val uri = Uri.parse(value)
        if (uri.scheme != "https" || uri.host.isNullOrBlank() ||
            !uri.path.isNullOrEmpty() || uri.query != null || uri.fragment != null ||
            uri.userInfo != null) return false
        context.getSharedPreferences("CivicCast", Context.MODE_PRIVATE)
            .edit().putString("stationAddress", value).apply()
        baseUrl = value
        return true
    }
}
