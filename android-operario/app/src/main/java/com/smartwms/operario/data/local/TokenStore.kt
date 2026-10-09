// data/local/TokenStore.kt
// Almacena el JWT y el rol en DataStore (reemplaza SharedPreferences)

package com.smartwms.operario.data.local

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import org.json.JSONArray
import org.json.JSONObject

// Extension para crear DataStore como singleton en el contexto de la app
val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "smartwms_prefs")

class TokenStore(private val context: Context) {

    companion object {
        val KEY_TOKEN = stringPreferencesKey("access_token")
        val KEY_ROLE  = stringPreferencesKey("role")
        val KEY_EMAIL = stringPreferencesKey("email")
        val KEY_ACTIVE_ORDER_ID = stringPreferencesKey("active_order_id")
        val KEY_ACTIVE_ORDER_START = stringPreferencesKey("active_order_start")
        val KEY_PICKED_SKUS = stringPreferencesKey("picked_skus") // JSON Map: { orderId: {sku1: qty, sku2: qty} }
    }

    suspend fun saveCredentials(token: String, role: String, email: String) {
        context.dataStore.edit { prefs ->
            prefs[KEY_TOKEN] = token
            prefs[KEY_ROLE]  = role
            prefs[KEY_EMAIL] = email
        }
    }

    suspend fun getToken(): String? =
        context.dataStore.data.map { it[KEY_TOKEN] }.first()

    suspend fun getRole(): String? =
        context.dataStore.data.map { it[KEY_ROLE] }.first()

    suspend fun getEmail(): String? =
        context.dataStore.data.map { it[KEY_EMAIL] }.first()

    suspend fun clear() {
        context.dataStore.edit { it.clear() }
    }

    /** Helper para obtener el header "Bearer <token>" listo para Retrofit */
    suspend fun bearerToken(): String = "Bearer ${getToken() ?: ""}"

    // ─── PERSISTENCIA DEL PEDIDO ACTIVO Y PICKING ───

    suspend fun saveActiveOrderId(orderId: Int?, startTime: Long? = null) {
        context.dataStore.edit { prefs ->
            if (orderId != null) {
                prefs[KEY_ACTIVE_ORDER_ID] = orderId.toString()
                if (startTime != null) {
                    prefs[KEY_ACTIVE_ORDER_START] = startTime.toString()
                } else if (!prefs.contains(KEY_ACTIVE_ORDER_START)) {
                    prefs[KEY_ACTIVE_ORDER_START] = System.currentTimeMillis().toString()
                }
            } else {
                prefs.remove(KEY_ACTIVE_ORDER_ID)
                prefs.remove(KEY_ACTIVE_ORDER_START)
            }
        }
    }

    suspend fun getActiveOrderId(): Int? {
        val idStr = context.dataStore.data.map { it[KEY_ACTIVE_ORDER_ID] }.first()
        return idStr?.toIntOrNull()
    }

    suspend fun getActiveOrderStartTime(): Long? {
        val timeStr = context.dataStore.data.map { it[KEY_ACTIVE_ORDER_START] }.first()
        return timeStr?.toLongOrNull()
    }

    suspend fun savePickedSkus(orderId: Int, pickedMap: Map<String, Int>) {
        val currentJsonStr = context.dataStore.data.map { it[KEY_PICKED_SKUS] }.first() ?: "{}"
        val json = try { JSONObject(currentJsonStr) } catch (e: Exception) { JSONObject() }
        
        val mapObj = JSONObject()
        pickedMap.forEach { (sku, qty) -> mapObj.put(sku, qty) }
        json.put(orderId.toString(), mapObj)
        
        context.dataStore.edit { prefs ->
            prefs[KEY_PICKED_SKUS] = json.toString()
        }
    }

    suspend fun getPickedSkus(orderId: Int): Map<String, Int> {
        val currentJsonStr = context.dataStore.data.map { it[KEY_PICKED_SKUS] }.first() ?: "{}"
        val json = try { JSONObject(currentJsonStr) } catch (e: Exception) { JSONObject() }
        
        if (!json.has(orderId.toString())) return emptyMap()
        
        val map = mutableMapOf<String, Int>()
        try {
            val mapObj = json.getJSONObject(orderId.toString())
            for (key in mapObj.keys()) {
                map[key] = mapObj.getInt(key)
            }
        } catch (e: Exception) {
            // Ignorar array legacy
        }
        return map
    }
}
