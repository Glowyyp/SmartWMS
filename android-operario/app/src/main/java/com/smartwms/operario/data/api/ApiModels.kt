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
    @SerializedName("access_token") val accessToken: String? = null,
    @SerializedName("token_type")   val tokenType: String? = null,
    val role: String,
    @SerializedName("mfa_required") val mfaRequired: Boolean = false,
    @SerializedName("mfa_token")    val mfaToken: String? = null,
    val stage: String? = null       // "verify" | "setup"
)

// Modelos para Autenticación Multifactor (MFA / TOTP)
data class MfaVerifyRequest(
    val code: String,
    @SerializedName("mfa_token") val mfaToken: String
)

data class MfaActivateRequest(
    val code: String,
    @SerializedName("mfa_token") val mfaToken: String? = null
)

data class MfaRecoverRequest(
    @SerializedName("recovery_code") val recoveryCode: String,
    @SerializedName("mfa_token")     val mfaToken: String
)

data class MfaSetupResponse(
    val secret: String,
    @SerializedName("provisioning_uri") val provisioningUri: String,
    @SerializedName("qr_code_svg")      val qrCodeSvg: String,
    @SerializedName("recovery_codes")   val recoveryCodes: List<String>,
    val issuer: String,
    @SerializedName("account_name")     val accountName: String
)

data class MfaStatusResponse(
    @SerializedName("mfa_enabled") val mfaEnabled: Boolean,
    @SerializedName("remaining_recovery_codes") val remainingRecoveryCodes: Int,
    @SerializedName("enabled_at") val enabledAt: String? = null
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
    @SerializedName("available_qty")      val availableQty: Int = 0,
    val length: Double? = null,
    val width: Double? = null,
    val height: Double? = null,
    @SerializedName("dimensions_unit")    val dimensionsUnit: String = "cm",
    val weight: Double? = null,
    @SerializedName("weight_unit")        val weightUnit: String = "kg",
    @SerializedName("estimated_volume")   val estimatedVolume: Double? = null,
    @SerializedName("has_box")            val hasBox: Boolean = true
)

// ─── Chat ─────────────────────────────────────────────────────────────────────

data class ChatRequest(
    @SerializedName("text") val text: String,
    @SerializedName("message") val message: String = text
) {
    constructor(input: String) : this(text = input, message = input)
}

data class ChatButton(
    val label: String,
    val cmd: String
)

data class ChatReply(
    val text: String = "",
    val buttons: List<ChatButton>? = null
)

data class ChatResponse(
    val reply: ChatReply? = null,
    val response: String? = null
) {
    fun getDisplayText(): String {
        return reply?.text?.takeIf { it.isNotBlank() }
            ?: response?.takeIf { it.isNotBlank() }
            ?: "(sin respuesta)"
    }
}

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
    @SerializedName("total_weight")             val totalWeight: Double?,
    @SerializedName("total_volume")             val totalVolume: Double?,
    @SerializedName("packages_count")           val packagesCount: Int?,
    val items: List<WorkOrderItem>
)

data class DispatchPackageIn(
    val length: Double? = null,
    val width: Double? = null,
    val height: Double? = null,
    val weight: Double? = null
)

data class DispatchIn(
    val packages: List<DispatchPackageIn> = emptyList(),
    @SerializedName("total_weight") val totalWeight: Double? = null,
    @SerializedName("total_volume") val totalVolume: Double? = null
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
