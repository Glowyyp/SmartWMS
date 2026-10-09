// data/api/RetrofitClient.kt
// Singleton que crea las instancias de Retrofit para backend (8001) y bot (8000)

package com.smartwms.operario.data.api

import com.smartwms.operario.BuildConfig
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.TimeUnit

object RetrofitClient {

    private val loggingInterceptor = HttpLoggingInterceptor().apply {
        level = HttpLoggingInterceptor.Level.BODY
    }

    private val okHttpClient = OkHttpClient.Builder()
        .addInterceptor(loggingInterceptor)
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

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
