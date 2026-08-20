package com.civiccast.mobile

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * Thin OkHttp wrapper around the CivicCast public app config endpoint.
 *
 * Single-purpose by design — the starter only needs one GET. As soon as we add a second
 * endpoint, refactor to Retrofit + a sealed Result type.
 */
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
    }

    suspend fun fetchAppConfig(): ConfigResponse = withContext(Dispatchers.IO) {
        val url = "${baseUrl.trimEnd('/')}/api/public/app/config"
        val request = Request.Builder()
            .url(url)
            .header("Accept", "application/json")
            .header("User-Agent", "CivicCastMobile/${BuildConfig.VERSION_NAME}")
            .get()
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw RuntimeException("HTTP ${response.code} from $url")
            }
            val body = response.body?.string()
                ?: throw RuntimeException("Empty body from $url")
            json.decodeFromString(ConfigResponse.serializer(), body)
        }
    }
}
