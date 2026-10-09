// data/api/ApiModels.kt
// Modelos de datos (Kotlin data classes que mapean la API REST de SmartWMS)

package com.smartwms.operario.data.api

import com.google.gson.annotations.SerializedName

// ─── Autenticacion ────────────────────────────────────────────────────────────

data class LoginRequest(
    val username: String,   // FastAPI OAuth2PasswordRequestForm usa "username"
    val password: String
)

data class LoginResponse(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("token_type")   val tokenType: String,
    val role: String
)

// ─── Inventario ───────────────────────────────────────────────────────────────

data class Product(
    val id: Int,
    val sku: String,
    @SerializedName("product_name")       val productName: String,
    @SerializedName("stock_quantity")     val stockQuantity: Int,
    @SerializedName("unit_price")         val unitPrice: Double,
    @SerializedName("reorder_point")      val reorderPoint: Int,
    @SerializedName("is_low_stock")       val isLowStock: Boolean,
    @SerializedName("warehouse_location") val warehouseLocation: String?,  // Zona física (A, B, C, D)
    @SerializedName("reserved_qty")       val reservedQty: Int = 0,
    @SerializedName("available_qty")      val availableQty: Int = 0
)

// ─── Chat ─────────────────────────────────────────────────────────────────────

data class ChatRequest(val message: String)

data class ChatResponse(val response: String)

// ─── Work Orders (Pedidos de Bodega) ─────────────────────────────────────────

data class WorkOrderItem(
    val id: Int,
    val sku: String,
    @SerializedName("product_name") val productName: String,
    val quantity: Int
)

data class WorkOrder(
    val id: Int,
    @SerializedName("order_number")            val orderNumber: String,
    val status: String,                         // "pending" | "dispatched" | "cancelled"
    @SerializedName("created_by_email")         val createdByEmail: String?,
    @SerializedName("assigned_operario_email")  val assignedOperarioEmail: String?,
    @SerializedName("dispatched_by_email")      val dispatchedByEmail: String?,
    @SerializedName("created_at")               val createdAt: String,
    @SerializedName("dispatched_at")            val dispatchedAt: String?,
    @SerializedName("cancelled_at")             val cancelledAt: String?,
    val items: List<WorkOrderItem>
)

// ─── Picking (local, sin endpoint real aun) ───────────────────────────────────

data class PickingItem(
    val sku: String,
    val productName: String,
    val quantity: Int,
    val location: String,
    val pickedQuantity: Int = 0
) {
    val isPicked: Boolean
        get() = pickedQuantity >= quantity
}
