// data/api/ApiService.kt
// Interfaz Retrofit que define los endpoints de SmartWMS

package com.smartwms.operario.data.api

import retrofit2.Response
import retrofit2.http.*

interface ApiService {

    // ── Autenticacion ─────────────────────────────────────────────────────────
    @FormUrlEncoded
    @POST("api/auth/login")
    suspend fun login(
        @Field("username") username: String,
        @Field("password") password: String
    ): Response<LoginResponse>

    // ── Inventario ────────────────────────────────────────────────────────────
    // Incluye warehouse_location para mostrar la zona de cada SKU al operario
    @GET("api/v1/inventory")
    suspend fun getInventory(
        @Header("Authorization") token: String
    ): Response<List<Product>>

    // ── Work Orders (Pedidos de Bodega) ───────────────────────────────────────

    /**
     * Lista pedidos filtrados por estado y/o por el email del operario asignado.
     * - status: "pending" | "dispatched" | "cancelled" | null (todos)
     * - assigned_to: email del operario → solo muestra sus pedidos (y los sin asignar)
     */
    @GET("api/v1/work-orders")
    suspend fun getWorkOrders(
        @Header("Authorization") token: String,
        @Query("status") status: String? = null,
        @Query("assigned_to") assignedTo: String? = null
    ): Response<List<WorkOrder>>

    /**
     * Despacha un pedido: descuenta el stock físico y lo marca como 'dispatched'.
     * Solo puede llamarse sobre pedidos en estado 'pending'.
     */
    @POST("api/v1/work-orders/{id}/dispatch")
    suspend fun dispatchWorkOrder(
        @Header("Authorization") token: String,
        @Path("id") orderId: Int
    ): Response<WorkOrder>

    // ── Chat (bot en puerto 8000) ─────────────────────────────────────────────
    @POST("api/chat")
    suspend fun sendChat(
        @Header("Authorization") token: String,
        @Body request: ChatRequest
    ): Response<ChatResponse>
}
