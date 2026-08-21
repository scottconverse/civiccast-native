package com.civiccast.tv

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNamingStrategy
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

class NetworkClient(
    private val baseUrl: String = BuildConfig.API_BASE_URL
) {
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    private val json: Json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        namingStrategy = JsonNamingStrategy.SnakeCase
    }

    suspend fun fetchAppConfig(): ConfigResponse = withContext(Dispatchers.IO) {
        val url = "${baseUrl.trimEnd('/')}/api/public/app/config"
        get(url, ConfigResponse.serializer())
    }

    /**
     * `liveStateUrl` is a path relative to [baseUrl] (e.g.
     * "/api/public/app/channels/public/live"), not an absolute URL.
     */
    suspend fun fetchLiveState(liveStateUrl: String): LiveState = withContext(Dispatchers.IO) {
        val url = if (liveStateUrl.startsWith("http")) {
            liveStateUrl
        } else {
            "${baseUrl.trimEnd('/')}/${liveStateUrl.trimStart('/')}"
        }
        get(url, LiveState.serializer())
    }

    private fun <T> get(url: String, serializer: kotlinx.serialization.KSerializer<T>): T {
        val request = Request.Builder()
            .url(url)
            .header("Accept", "application/json")
            .header("User-Agent", "CivicCastTV/${BuildConfig.VERSION_NAME}")
            .get()
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw RuntimeException("HTTP ${response.code} from $url")
            }
            val body = response.body?.string()
                ?: throw RuntimeException("Empty body from $url")
            return json.decodeFromString(serializer, body)
        }
    }
}
