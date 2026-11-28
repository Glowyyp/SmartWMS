// ui/fragments/PickingFragment.kt
// Lista de pedidos de bodega y detalle de picking para el operario.
// Los pedidos provienen de la API real (filtrados por email del operario logueado).

package com.smartwms.operario.ui.fragments

import android.app.AlertDialog
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.recyclerview.widget.LinearLayoutManager
import com.smartwms.operario.data.api.PickingItem
import com.smartwms.operario.data.api.WorkOrder
import com.smartwms.operario.databinding.FragmentPickingBinding
import com.smartwms.operario.ui.OrderViewModel
import com.smartwms.operario.ui.PickingScanAccumulator
import com.smartwms.operario.ui.SmartCaptureActivity
import com.smartwms.operario.ui.adapters.PickingAdapter
import com.smartwms.operario.ui.adapters.WorkOrderAdapter
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanIntentResult
import androidx.navigation.fragment.findNavController
import com.smartwms.operario.R
import android.widget.EditText
import android.widget.FrameLayout
import android.text.InputType
import android.graphics.Color

class PickingFragment : Fragment() {

    private var _binding: FragmentPickingBinding? = null
    private val binding get() = _binding!!

    // activityViewModels() comparte la misma instancia con otros fragmentos
    private val orderVm: OrderViewModel by activityViewModels()

    private lateinit var workOrderAdapter: WorkOrderAdapter
    private lateinit var pickingAdapter: PickingAdapter

    // Feedback visual instantáneo sin acumulación de Toasts en escaneos rápidos
    private val feedbackHandler = Handler(Looper.getMainLooper())
    private var hideFeedbackRunnable: Runnable? = null
    private var activeToast: Toast? = null

    // Launcher para escanear código de pedido (QR o Código de barras)
    private val orderScanLauncher = registerForActivityResult(ScanContract()) { result: ScanIntentResult ->
        if (result.contents != null) {
            processOrderCode(result.contents)
        }
    }

    // Launcher para el escáner de productos (QR o Código de barras ZXing multiformato)
    private val qrLauncher = registerForActivityResult(ScanContract()) { result: ScanIntentResult ->
        if (result.contents != null) {
            processProductCode(result.contents)
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentPickingBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        setupOrdersList()
        setupPickingDetail()
        observeViewModel()

        // Refrescar manualmente
        binding.btnRefreshOrders.setOnClickListener {
            orderVm.loadPendingOrders()
            orderVm.loadAllOrders()
        }
    }

    // ── VISTA 1: Lista de pedidos ─────────────────────────────────────────────

    private fun setupOrdersList() {
        workOrderAdapter = WorkOrderAdapter(emptyList()) { order ->
            orderVm.selectOrder(order)
        }
        binding.rvWorkOrders.layoutManager = LinearLayoutManager(requireContext())
        binding.rvWorkOrders.adapter = workOrderAdapter

        // Escanear código de pedido (QR o Barras)
        binding.btnScanOrder.setOnClickListener {
            orderScanLauncher.launch(
                SmartCaptureActivity.buildScanOptions("Escanea el código del pedido (QR o Barras)")
            )
        }

        // Ingreso manual de código de pedido
        binding.btnManualOrder.setOnClickListener {
            showManualOrderDialog()
        }
    }

    // ── VISTA 2: Detalle del pedido activo ────────────────────────────────────

    private fun setupPickingDetail() {
        pickingAdapter = PickingAdapter(
            items = mutableListOf(),
            onLocationClick = { sku, location ->
                showLocationDialog(sku, location)
            }
        )

        binding.rvPickingItems.layoutManager = LinearLayoutManager(requireContext())
        binding.rvPickingItems.adapter = pickingAdapter

        // Botón Escáner de producto (compatible con QR y Código de barras 1D)
        binding.btnScanQr.setOnClickListener {
            qrLauncher.launch(
                SmartCaptureActivity.buildScanOptions("Escanea el código del producto (QR o Barras)")
            )
        }

        // Botón Ingreso manual de código de producto
        binding.btnManualCode.setOnClickListener {
            showManualProductDialog()
        }

        // Botón volver a la lista
        binding.btnBackToList.setOnClickListener {
            orderVm.clearSelectedOrder()
        }
    }

    // ── OBSERVADORES ─────────────────────────────────────────────────────────

    private fun observeViewModel() {
        // Lista de pedidos pendientes
        orderVm.workOrders.observe(viewLifecycleOwner) { orders ->
            workOrderAdapter.updateOrders(orders)

            val isEmpty = orders.isEmpty()
            binding.layoutEmptyOrders.visibility = if (isEmpty) View.VISIBLE else View.GONE
            binding.rvWorkOrders.visibility = if (isEmpty) View.GONE else View.VISIBLE

            // Si el pedido seleccionado ya no está en la lista de pendientes (ej. despachado), deseleccionar automáticamente
            val currentSelected = orderVm.selectedOrder.value
            if (currentSelected != null && orders.none { it.id == currentSelected.id }) {
                orderVm.clearSelectedOrder()
            }
        }

        // Pedido seleccionado → cambiar entre vistas
        orderVm.selectedOrder.observe(viewLifecycleOwner) { order ->
            if (order == null || order.status != "pending") {
                showOrdersList()
            } else {
                showOrderDetail(order)
            }
        }

        // Estado de picking (persiste a través de la app)
        orderVm.pickedSkus.observe(viewLifecycleOwner) { pickedMap ->
            val order = orderVm.selectedOrder.value
            if (order != null) {
                if (orderVm.isPickingComplete() && order.status == "pending") {
                    // Si al abrir la vista ya está completo, redirigir directo
                    findNavController().popBackStack(R.id.homeFragment, false)
                    findNavController().navigate(R.id.packingFragment)
                    return@observe
                }
                renderPickingList(order, pickedMap)
            }
        }

        // Loading
        orderVm.isLoading.observe(viewLifecycleOwner) { loading ->
            binding.progressOrdersLoading.visibility = if (loading) View.VISIBLE else View.GONE
        }

        // Errores
        orderVm.error.observe(viewLifecycleOwner) { error ->
            if (error != null) {
                binding.tvOrdersError.text = error
                binding.tvOrdersError.visibility = View.VISIBLE
                orderVm.clearError()
            } else {
                binding.tvOrdersError.visibility = View.GONE
            }
        }

        // Resultado de despacho exitoso
        orderVm.dispatchResult.observe(viewLifecycleOwner) { dispatched ->
            if (dispatched != null) {
                Toast.makeText(
                    requireContext(),
                    "✅ Pedido ${dispatched.orderNumber} despachado. Stock actualizado.",
                    Toast.LENGTH_LONG
                ).show()
                orderVm.clearDispatchResult()
                // Volver a la lista de pedidos
                orderVm.clearSelectedOrder()
            }
        }
    }

    // ── HELPERS DE NAVEGACIÓN ─────────────────────────────────────────────────

    private fun showOrdersList() {
        binding.layoutOrdersList.visibility   = View.VISIBLE
        binding.layoutOrderDetail.visibility  = View.GONE
    }

    private fun showOrderDetail(order: WorkOrder) {
        binding.layoutOrdersList.visibility   = View.GONE
        binding.layoutOrderDetail.visibility  = View.VISIBLE

        binding.tvOrderId.text = order.orderNumber

        val pickedMap = orderVm.pickedSkus.value ?: emptyMap()
        renderPickingList(order, pickedMap)

        // No hay botón Confirmar Despacho en Picking
    }

    private fun renderPickingList(order: WorkOrder, pickedMap: Map<String, Int>) {
        // Consolidar ítems repetidos por SKU para mostrar un único registro acumulado por producto
        val grouped = LinkedHashMap<String, PickingItem>()
        for (item in order.items) {
            val existing = grouped[item.sku]
            if (existing == null) {
                val pickedQty = pickedMap[item.sku] ?: 0
                grouped[item.sku] = PickingItem(
                    sku            = item.sku,
                    productName    = item.productName,
                    quantity       = item.quantity,
                    location       = orderVm.getSkuLocation(item.sku) ?: "",
                    pickedQuantity = pickedQty
                )
            } else {
                grouped[item.sku] = existing.copy(quantity = existing.quantity + item.quantity)
            }
        }
        val newList = grouped.values.toList()
        pickingAdapter.updateItems(newList)

        val totalUnits = newList.sumOf { it.quantity }
        val doneUnits  = newList.sumOf { minOf(it.pickedQuantity, it.quantity) }
        val totalLines = newList.size
        val doneLines  = newList.count { it.isPicked }
        val pct        = if (totalUnits > 0) (doneUnits * 100) / totalUnits else 0

        binding.progressPicking.progress = pct
        binding.tvProgress.text = "$pct% completado ($doneUnits/$totalUnits uds · $doneLines/$totalLines SKUs)"
    }

    // ── LECTURA E INGRESO MANUAL DE PEDIDO ────────────────────────────────────

    private fun showManualOrderDialog() {
        val input = EditText(requireContext()).apply {
            hint = "Ej: WO-0001 o 1"
            inputType = InputType.TYPE_CLASS_TEXT
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
        }
        val container = FrameLayout(requireContext()).apply {
            val params = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            params.setMargins(50, 20, 50, 10)
            input.layoutParams = params
            addView(input)
        }

        AlertDialog.Builder(requireContext())
            .setTitle("⌨️ Ingresar Código de Pedido")
            .setMessage("Escribe el número de pedido para abrirlo:")
            .setView(container)
            .setPositiveButton("Abrir Pedido") { _, _ ->
                val code = input.text.toString().trim()
                if (code.isNotEmpty()) {
                    processOrderCode(code)
                } else {
                    Toast.makeText(requireContext(), "Debes ingresar un número de pedido.", Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun processOrderCode(rawCode: String) {
        val clean = rawCode.trim()
        if (clean.isEmpty()) return

        // Normalizar si se ingresa solo el número secuencial (ej: 1 -> WO-0001)
        val normalized = if (clean.all { it.isDigit() }) {
            String.format(java.util.Locale.US, "WO-%04d", clean.toInt())
        } else {
            clean
        }

        val pendingList = orderVm.workOrders.value ?: emptyList()
        val order = pendingList.find {
            it.orderNumber.equals(normalized, ignoreCase = true) ||
            it.orderNumber.equals(clean, ignoreCase = true) ||
            it.id.toString() == clean
        }

        if (order != null) {
            orderVm.selectOrder(order)
            Toast.makeText(requireContext(), "✓ Pedido ${order.orderNumber} cargado para picking", Toast.LENGTH_SHORT).show()
            return
        }

        // Si no está en pendientes, buscar en el historial general para retroalimentar con precisión
        val allList = orderVm.allOrders.value ?: emptyList()
        val historicalOrder = allList.find {
            it.orderNumber.equals(normalized, ignoreCase = true) ||
            it.orderNumber.equals(clean, ignoreCase = true) ||
            it.id.toString() == clean
        }

        if (historicalOrder != null) {
            when (historicalOrder.status) {
                "dispatched" -> {
                    AlertDialog.Builder(requireContext())
                        .setTitle("⚠️ Pedido ya Despachado")
                        .setMessage("El pedido ${historicalOrder.orderNumber} ya fue procesado y despachado con anterioridad.")
                        .setPositiveButton("OK", null)
                        .show()
                }
                "cancelled" -> {
                    AlertDialog.Builder(requireContext())
                        .setTitle("❌ Pedido Cancelado")
                        .setMessage("El pedido ${historicalOrder.orderNumber} fue cancelado por el supervisor y no está disponible para picking.")
                        .setPositiveButton("OK", null)
                        .show()
                }
                else -> {
                    AlertDialog.Builder(requireContext())
                        .setTitle("⚠️ Pedido No Disponible")
                        .setMessage("El pedido ${historicalOrder.orderNumber} se encuentra en estado '${historicalOrder.status}' y no está asignado a tu usuario para picking.")
                        .setPositiveButton("OK", null)
                        .show()
                }
            }
        } else {
            AlertDialog.Builder(requireContext())
                .setTitle("❌ Pedido No Encontrado")
                .setMessage("El código de pedido '$clean' no existe en el sistema o no corresponde a tus pedidos asignados.")
                .setPositiveButton("OK", null)
                .show()
        }
    }

    // ── LECTURA E INGRESO MANUAL DE PRODUCTO (SKU / BARRAS / QR) ──────────────

    private fun showManualProductDialog() {
        val input = EditText(requireContext()).apply {
            hint = "Ej: SKU-001 o código de barras"
            inputType = InputType.TYPE_CLASS_TEXT
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
        }
        val container = FrameLayout(requireContext()).apply {
            val params = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            params.setMargins(50, 20, 50, 10)
            input.layoutParams = params
            addView(input)
        }

        AlertDialog.Builder(requireContext())
            .setTitle("⌨️ Ingreso Manual de Producto")
            .setMessage("Ingresa el código SKU o código de barras del producto:")
            .setView(container)
            .setPositiveButton("Validar Código") { _, _ ->
                val code = input.text.toString().trim()
                if (code.isNotEmpty()) {
                    processProductCode(code)
                } else {
                    Toast.makeText(requireContext(), "Debes ingresar un código de producto.", Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    /**
     * Al escanear el código QR/barras o ingresar manualmente un SKU válido,
     * marca automáticamente la cantidad total requerida de ese SKU (ej. 500/500)
     * sin solicitar cantidad manual ni exigir escaneos repetidos.
     */
    private fun processProductCode(scannedOrManualCode: String) {
        val order = orderVm.selectedOrder.value ?: return

        when (val result = orderVm.registerProductScan(scannedOrManualCode)) {
            is PickingScanAccumulator.ScanResult.EmptyCode -> {
                showQuickToast("Código vacío.")
            }
            is PickingScanAccumulator.ScanResult.InvalidCode -> {
                AlertDialog.Builder(requireContext())
                    .setTitle("❌ Código Inválido")
                    .setMessage("El producto con código '${result.rawCode}' no pertenece a este pedido (${order.orderNumber}).")
                    .setPositiveButton("OK", null)
                    .show()
            }
            is PickingScanAccumulator.ScanResult.AlreadyComplete -> {
                AlertDialog.Builder(requireContext())
                    .setTitle("⚠️ Producto completado")
                    .setMessage("Ya recolectaste todas las unidades requeridas de ${result.productName} (${result.requiredQuantity}/${result.requiredQuantity}).")
                    .setPositiveButton("OK", null)
                    .show()
            }
            is PickingScanAccumulator.ScanResult.Added -> {
                pickingAdapter.setLastScannedSku(result.sku)

                if (result.orderComplete) {
                    showQuickToast("✅ Picking completado: ${result.productName} (${result.newQuantity}/${result.requiredQuantity})")
                    findNavController().popBackStack(R.id.homeFragment, false)
                    findNavController().navigate(R.id.packingFragment)
                } else {
                    val feedbackText = "✓ ${result.productName} completado (${result.newQuantity} / ${result.requiredQuantity} uds)"
                    showScanFeedbackBanner(feedbackText)
                    showQuickToast("✓ ${result.productName} (${result.newQuantity}/${result.requiredQuantity})")
                }
            }
        }
    }

    private fun showScanFeedbackBanner(message: String) {
        val b = _binding ?: return
        hideFeedbackRunnable?.let { feedbackHandler.removeCallbacks(it) }
        b.tvScanFeedback.text = message
        b.tvScanFeedback.visibility = View.VISIBLE
        val runnable = Runnable {
            _binding?.tvScanFeedback?.visibility = View.GONE
        }
        hideFeedbackRunnable = runnable
        feedbackHandler.postDelayed(runnable, 2800L)
    }

    private fun showQuickToast(message: String) {
        activeToast?.cancel()
        activeToast = Toast.makeText(requireContext(), message, Toast.LENGTH_SHORT).also { it.show() }
    }

    // ── DIÁLOGO DE LOCALIZACIÓN ❓ ────────────────────────────────────────────

    /**
     * Muestra la ubicación física del SKU.
     * La ubicación proviene del campo warehouse_location del inventario:
     *   Layout del Supervisor → warehouse_location → Android Operario
     * Fuente única de verdad.
     */
    private fun showLocationDialog(sku: String, location: String?) {
        val message = if (!location.isNullOrBlank()) {
            "📍 Zona del almacén:\n\n${location}\n\n(Según el Layout del almacén)"
        } else {
            "Este SKU todavía no tiene una ubicación registrada.\n\n" +
            "El Supervisor puede asignarla desde la sección Inventario."
        }

        AlertDialog.Builder(requireContext())
            .setTitle("Ubicación de $sku")
            .setMessage(message)
            .setPositiveButton("Cerrar", null)
            .show()
    }

    override fun onResume() {
        super.onResume()
        // Si el pedido seleccionado ya no está pendiente o fue completado/despachado, limpiar selección
        val current = orderVm.selectedOrder.value
        if (current != null && current.status != "pending") {
            orderVm.clearSelectedOrder()
        }
        orderVm.loadPendingOrders()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        hideFeedbackRunnable?.let { feedbackHandler.removeCallbacks(it) }
        hideFeedbackRunnable = null
        activeToast?.cancel()
        activeToast = null
        _binding = null
    }
}
