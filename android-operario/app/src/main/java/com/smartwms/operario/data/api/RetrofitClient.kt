// data/api/RetrofitClient.kt
// Singleton que crea las instancias de Retrofit para backend (8001) y bot (8000)

package com.smartwms.operario.data.api

import android.content.Context
import com.smartwms.operario.BuildConfig
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.net.URI
import java.util.concurrent.TimeUnit

class HostSelectionInterceptor : Interceptor {
    @Volatile var host: String? = null
    @Volatile var scheme: String? = null
    @Volatile var backendPort: Int? = null
    @Volatile var botPort: Int = 8000

    override fun intercept(chain: Interceptor.Chain): Response {
        var request = chain.request()
        val currentHost = host
        if (!currentHost.isNullOrEmpty()) {
            val newUrlBuilder = request.url.newBuilder()
                .host(currentHost)
            scheme?.let { newUrlBuilder.scheme(it) }

            // Distinguir llamadas al bot (puerto 8000 o ruta que contiene chat)
            val isBotRequest = request.url.port == 8000 || request.url.encodedPath.contains("chat")
            val targetPort = if (isBotRequest) {
                botPort
            } else {
                backendPort ?: request.url.port
            }
            newUrlBuilder.port(targetPort)

            request = request.newBuilder()
                .url(newUrlBuilder.build())
                .build()
        }
        return chain.proceed(request)
    }
}

object RetrofitClient {

    private val loggingInterceptor = HttpLoggingInterceptor().apply {
        level = HttpLoggingInterceptor.Level.BODY
    }

    val hostInterceptor = HostSelectionInterceptor()

    private val okHttpClient = OkHttpClient.Builder()
        .addInterceptor(hostInterceptor)
        .addInterceptor(loggingInterceptor)
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    fun init(context: Context) {
        val prefs = context.getSharedPreferences("smartwms_network", Context.MODE_PRIVATE)
        val saved = prefs.getString("server_url", null)
        if (!saved.isNullOrBlank()) {
            setServerAddress(saved)
        }
    }

    fun getServerAddress(context: Context): String {
        val prefs = context.getSharedPreferences("smartwms_network", Context.MODE_PRIVATE)
        return prefs.getString("server_url", null) ?: BuildConfig.API_BASE_URL
    }

    fun setServerAddress(fullUrlOrIp: String) {
        var clean = fullUrlOrIp.trim()
        if (!clean.startsWith("http://") && !clean.startsWith("https://")) {
            clean = "http://$clean"
        }
        try {
            val uri = URI(clean)
            if (!uri.host.isNullOrEmpty()) {
                hostInterceptor.host = uri.host
                hostInterceptor.scheme = uri.scheme ?: "http"
                if (uri.port != -1) {
                    hostInterceptor.backendPort = uri.port
                }
                hostInterceptor.botPort = 8000
            }
        } catch (_: Exception) {}
    }

    // API del Backend (puerto 8001)
    val apiService: ApiService by lazy {
        Retrofit.Builder()
            .baseUrl(BuildConfig.API_BASE_URL + "/")
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(ApiService::class.java)
    }

    // API del Bot (puerto 8000) — mismo ApiService, distinta base URL
    val botService: ApiService by lazy {
        Retrofit.Builder()
            .baseUrl(BuildConfig.BOT_BASE_URL + "/")
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(ApiService::class.java)
    }
}
