// ui/OrderViewModel.kt
// ViewModel compartido entre todos los fragments.
// Carga pedidos de bodega REALES desde la API del backend.
// Filtra por el email del operario logueado para mostrar solo sus pedidos asignados.

package com.smartwms.operario.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import com.smartwms.operario.data.api.ApiService
import com.smartwms.operario.data.api.Product
import com.smartwms.operario.data.api.RetrofitClient
import com.smartwms.operario.data.api.WorkOrder
import com.smartwms.operario.data.local.TokenStore
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

class OrderViewModel(application: Application) : AndroidViewModel(application) {

    private val tokenStore = TokenStore(application.applicationContext)
    private val api: ApiService = RetrofitClient.apiService

    // ── Estado: lista de pedidos pendientes asignados al operario ─────────────
    private val _workOrders = MutableLiveData<List<WorkOrder>>(emptyList())
    val workOrders: LiveData<List<WorkOrder>> = _workOrders

    // ── Estado: TODOS los pedidos (pendientes + despachados + cancelados) ──────
    // Usado por HistorialFragment y HomeFragment (historial de hoy)
    private val _allOrders = MutableLiveData<List<WorkOrder>>(emptyList())
    val allOrders: LiveData<List<WorkOrder>> = _allOrders

    // ── Estado: pedido actualmente seleccionado para despachar ────────────────
    private val _selectedOrder = MutableLiveData<WorkOrder?>(null)
    val selectedOrder: LiveData<WorkOrder?> = _selectedOrder

    // ── Estado: mapa de SKU → Product (con warehouse_location) ───────────────
    private val _inventoryMap = MutableLiveData<Map<String, Product>>(emptyMap())
    val inventoryMap: LiveData<Map<String, Product>> = _inventoryMap

    // ── Estado: loading y error ───────────────────────────────────────────────
    private val _isLoading = MutableLiveData(false)
    val isLoading: LiveData<Boolean> = _isLoading

    private val _error = MutableLiveData<String?>(null)
    val error: LiveData<String?> = _error

    private val _dispatchResult = MutableLiveData<WorkOrder?>(null)
    val dispatchResult: LiveData<WorkOrder?> = _dispatchResult

    // ── Info del usuario logueado (expuesta para HomeFragment) ────────────────
    var currentUserEmail: String = ""
        private set
    var currentUserRole: String = ""
        private set

    // ── Estado: SKUs recolectados para el pedido activo ───────────────────────
    private val _pickedSkus = MutableLiveData<Map<String, Int>>(emptyMap())
    val pickedSkus: LiveData<Map<String, Int>> = _pickedSkus

    init {
        loadUserInfo()
        loadInventory()
        loadPendingOrders()
        loadAllOrders()
        startPolling()
    }

    // ── INFO DEL USUARIO ──────────────────────────────────────────────────────
    private fun loadUserInfo() {
        viewModelScope.launch {
            currentUserEmail = tokenStore.getEmail() ?: ""
            currentUserRole  = tokenStore.getRole()  ?: "operario"
        }
    }

    // ── CARGA DE INVENTARIO ───────────────────────────────────────────────────
    /**
     * Carga el inventario completo para tener warehouse_location de cada SKU.
     * Esta es la misma fuente de datos que el Supervisor usa en Layout.
     */
    private fun loadInventory() {
        viewModelScope.launch {
            try {
                val token = tokenStore.bearerToken()
                val response = api.getInventory(token)
                if (response.isSuccessful) {
                    val map = response.body()?.associateBy { it.sku } ?: emptyMap()
                    _inventoryMap.postValue(map)
                }
            } catch (e: Exception) {
                // Inventario no crítico para el flujo — no bloqueamos al operario
            }
        }
    }

    /**
     * Devuelve la ubicación física de un SKU desde el inventario real.
     * Fuente única de verdad: mismo campo que usa el Layout del Supervisor.
     */
    fun getSkuLocation(sku: String): String? {
        return _inventoryMap.value?.get(sku)?.warehouseLocation
    }

    // ── CARGA DE PEDIDOS PENDIENTES ───────────────────────────────────────────
    /**
     * Carga los pedidos PENDIENTES asignados a ESTE operario.
     * Usa assigned_to=email para que el backend filtre:
     *   - Pedidos con assigned_operario_email == email del operario actual
     *   - Pedidos con assigned_operario_email == NULL (sin asignar, visible para todos)
     */
    fun loadPendingOrders() {
        viewModelScope.launch {
            _isLoading.postValue(true)
            _error.postValue(null)
            try {
                val token = tokenStore.bearerToken()
                val email = tokenStore.getEmail()
                val response = api.getWorkOrders(
                    token = token,
                    status = "pending",
                    assignedTo = email
                )
                if (response.isSuccessful) {
                    val orders = response.body() ?: emptyList()
                    _workOrders.postValue(orders)
                    // Restaurar pedido activo si existe y está en la lista de pendientes
                    val activeId = tokenStore.getActiveOrderId()
                    if (activeId != null && _selectedOrder.value == null) {
                        val activeOrder = orders.find { it.id == activeId }
                        if (activeOrder != null) {
                            _selectedOrder.postValue(activeOrder)
                            _pickedSkus.postValue(tokenStore.getPickedSkus(activeId))
                        } else {
                            tokenStore.saveActiveOrderId(null)
                        }
                    }
                } else {
                    _error.postValue("Error ${response.code()}: No se pudieron cargar los pedidos.")
                }
            } catch (e: Exception) {
                _error.postValue("Sin conexión al servidor. Verifica la red.")
            } finally {
                _isLoading.postValue(false)
            }
        }
    }

    // ── CARGA DE HISTORIAL COMPLETO ───────────────────────────────────────────
    /**
     * Carga TODOS los pedidos del operario (todos los estados).
     * Usado por HistorialFragment y HomeFragment (historial de hoy).
     */
    fun loadAllOrders() {
        viewModelScope.launch {
            try {
                val token = tokenStore.bearerToken()
                val email = tokenStore.getEmail()
                val response = api.getWorkOrders(
                    token = token,
                    status = null,
                    assignedTo = email
                )
                if (response.isSuccessful) {
                    _allOrders.postValue(response.body() ?: emptyList())
                }
            } catch (e: Exception) {
                // Silencioso — no bloquear la UI principal
            }
        }
    }

    // ── POLLING AUTOMÁTICO ────────────────────────────────────────────────────
    /**
     * Recarga pedidos cada 15 segundos para mantener sincronía con el Supervisor.
     * Si el Supervisor crea un pedido, aparece automáticamente en el Android.
     */
    private fun startPolling() {
        viewModelScope.launch {
            while (isActive) {
                delay(15_000L)
                try {
                    val token = tokenStore.bearerToken()
                    val email = tokenStore.getEmail()
                    val response = api.getWorkOrders(
                        token = token,
                        status = "pending",
                        assignedTo = email
                    )
                    if (response.isSuccessful) {
                        _workOrders.postValue(response.body() ?: emptyList())
                        loadInventory()
                    }
                } catch (_: Exception) { /* Silencioso */ }
            }
        }
    }

    // ── SELECCIÓN Y DESPACHO ──────────────────────────────────────────────────

    fun selectOrder(order: WorkOrder) {
        _selectedOrder.value = order
        viewModelScope.launch {
            val existingStart = tokenStore.getActiveOrderStartTime()
            tokenStore.saveActiveOrderId(order.id, existingStart ?: System.currentTimeMillis())
            _pickedSkus.postValue(tokenStore.getPickedSkus(order.id))
        }
    }

    fun clearSelectedOrder() {
        _selectedOrder.value = null
        _pickedSkus.value = emptyMap()
        viewModelScope.launch {
            tokenStore.saveActiveOrderId(null)
        }
    }

    fun addSkuPicked(sku: String, maxQuantity: Int, quantityToAdd: Int = 1): Boolean {
        val order = _selectedOrder.value ?: return false
        val current = _pickedSkus.value?.toMutableMap() ?: mutableMapOf()
        val currentQty = current[sku] ?: 0
        if (currentQty + quantityToAdd <= maxQuantity) {
            current[sku] = currentQty + quantityToAdd
            _pickedSkus.value = current
            viewModelScope.launch {
                tokenStore.savePickedSkus(order.id, current)
            }
            return true
        }
        return false
    }

    fun isPickingComplete(): Boolean {
        val order = _selectedOrder.value ?: return false
        val current = _pickedSkus.value ?: emptyMap()
        for (item in order.items) {
            val pickedQty = current[item.sku] ?: 0
            if (pickedQty < item.quantity) {
                return false
            }
        }
        return true
    }

    /**
     * Despacha el pedido activo.
     * La transacción en el backend descuenta el stock físico atómicamente.
     * Al despacharse, el pedido desaparece de la lista de pendientes.
     */
    fun dispatchSelectedOrder() {
        val order = _selectedOrder.value ?: return
        viewModelScope.launch {
            _isLoading.postValue(true)
            try {
                val token = tokenStore.bearerToken()
                val response = api.dispatchWorkOrder(token, order.id)
                if (response.isSuccessful) {
                    val dispatched = response.body()!!
                    _dispatchResult.postValue(dispatched)
                    _workOrders.postValue(
                        _workOrders.value?.filter { it.id != dispatched.id } ?: emptyList()
                    )
                    _selectedOrder.postValue(dispatched)
                    _pickedSkus.postValue(emptyMap())
                    tokenStore.saveActiveOrderId(null)
                    // Actualizar historial completo tras despacho
                    loadAllOrders()
                } else {
                    val errorBody = response.errorBody()?.string()
                    _error.postValue("Error al despachar: $errorBody")
                }
            } catch (e: Exception) {
                _error.postValue("Error de conexión: ${e.message}")
            } finally {
                _isLoading.postValue(false)
            }
        }
    }

    fun clearError() { _error.value = null }
    fun clearDispatchResult() { _dispatchResult.value = null }

    // ── COMPATIBILIDAD CON PickingFragment EXISTENTE ──────────────────────────
    // Mantiene la interfaz que PickingFragment ya usa con items/orderId
    // pero ahora conectado a la API real.

    val orderId: String get() = _selectedOrder.value?.orderNumber ?: "—"
}
