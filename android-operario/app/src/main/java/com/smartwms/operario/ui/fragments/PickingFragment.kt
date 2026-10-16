// ui/fragments/PickingFragment.kt
// Lista de pedidos de bodega y detalle de picking para el operario.
// Los pedidos provienen de la API real (filtrados por email del operario logueado).

package com.smartwms.operario.ui.fragments

import android.app.AlertDialog
import android.os.Bundle
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
import com.smartwms.operario.ui.adapters.PickingAdapter
import com.smartwms.operario.ui.adapters.WorkOrderAdapter
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.journeyapps.barcodescanner.ScanIntentResult
import androidx.navigation.fragment.findNavController
import com.smartwms.operario.R

class PickingFragment : Fragment() {

    private var _binding: FragmentPickingBinding? = null
    private val binding get() = _binding!!

    // activityViewModels() comparte la misma instancia con otros fragmentos
    private val orderVm: OrderViewModel by activityViewModels()

    private lateinit var workOrderAdapter: WorkOrderAdapter
    private lateinit var pickingAdapter: PickingAdapter

    // Ya no mantenemos estado duplicado local. El adapter usará el estado que le pasemos.

    // Launcher para el escáner QR de ZXing
    private val qrLauncher = registerForActivityResult(ScanContract()) { result: ScanIntentResult ->
        if (result.contents != null) {
            handleQrScan(result.contents)
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
        }
    }

    // ── VISTA 1: Lista de pedidos ─────────────────────────────────────────────

    private fun setupOrdersList() {
        workOrderAdapter = WorkOrderAdapter(emptyList()) { order ->
            orderVm.selectOrder(order)
        }
        binding.rvWorkOrders.layoutManager = LinearLayoutManager(requireContext())
        binding.rvWorkOrders.adapter = workOrderAdapter
    }

    // ── VISTA 2: Detalle del pedido activo ────────────────────────────────────

    private fun setupPickingDetail() {
        pickingAdapter = PickingAdapter(
            items = mutableListOf(), // Inicia vacío, pero modificable
            onLocationClick = { sku, location ->
                showLocationDialog(sku, location)
            }
        )

        binding.rvPickingItems.layoutManager = LinearLayoutManager(requireContext())
        binding.rvPickingItems.adapter = pickingAdapter

        // Botón QR Scanner
        binding.btnScanQr.setOnClickListener {
            val options = ScanOptions()
            options.setDesiredBarcodeFormats(ScanOptions.ALL_CODE_TYPES)
            options.setPrompt("Escanea el código del producto (SKU)")
            options.setCameraId(0)
            options.setBeepEnabled(true)
            options.setBarcodeImageEnabled(false)
            options.setOrientationLocked(false)
            qrLauncher.launch(options)
        }

        // Ya no hay botón Confirmar Despacho en Picking. Se redirige a Packing.

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
        val newList = order.items.map { item ->
            val pickedQty = pickedMap[item.sku] ?: 0
            PickingItem(
                sku            = item.sku,
                productName    = item.productName,
                quantity       = item.quantity,
                location       = orderVm.getSkuLocation(item.sku) ?: "",
                pickedQuantity = pickedQty
            )
        }
        pickingAdapter.updateItems(newList)

        val total = newList.size
        val done  = newList.count { it.isPicked }
        val pct   = if (total > 0) (done * 100) / total else 0

        binding.progressPicking.progress = pct
        binding.tvProgress.text = "$pct% completado ($done/$total)"
    }

    // ── PROCESAMIENTO DE QR ───────────────────────────────────────────────────

    private fun handleQrScan(scannedCode: String) {
        val cleanCode = scannedCode.trim()
        val order = orderVm.selectedOrder.value ?: return
        val item = order.items.find { it.sku.trim().equals(cleanCode, ignoreCase = true) }
        
        if (item == null) {
            AlertDialog.Builder(requireContext())
                .setTitle("❌ Código Inválido")
                .setMessage("El producto escaneado ($cleanCode) no pertenece a este pedido.")
                .setPositiveButton("OK", null)
                .show()
            return
        }

        val currentQty = orderVm.pickedSkus.value?.get(item.sku) ?: 0
        val pendingQty = item.quantity - currentQty

        if (pendingQty <= 0) {
            AlertDialog.Builder(requireContext())
                .setTitle("⚠️ Producto completado")
                .setMessage("Ya recolectaste todas las unidades requeridas de ${item.productName}.")
                .setPositiveButton("OK", null)
                .show()
            return
        }

        if (item.quantity == 1) {
            // Si solo se pidió 1, saltar el cuadro de texto y agregar directo
            processQuantityInput(item, 1)
        } else {
            // Mostrar input para solicitar cantidad
            showQuantityInputDialog(item, pendingQty)
        }
    }

    private fun showQuantityInputDialog(item: com.smartwms.operario.data.api.WorkOrderItem, pendingQty: Int) {
        val input = android.widget.EditText(requireContext())
        input.inputType = android.text.InputType.TYPE_CLASS_NUMBER
        input.hint = "Max: $pendingQty"
        
        // Estilo básico para el padding
        val container = android.widget.FrameLayout(requireContext())
        val params = android.widget.FrameLayout.LayoutParams(
            android.view.ViewGroup.LayoutParams.MATCH_PARENT,
            android.view.ViewGroup.LayoutParams.WRAP_CONTENT
        )
        params.setMargins(50, 20, 50, 0)
        input.layoutParams = params
        container.addView(input)

        AlertDialog.Builder(requireContext())
            .setTitle("Ingresar Cantidad")
            .setMessage("¿Cuántas unidades de ${item.productName} vas a recolectar?\n(Pendientes: $pendingQty)")
            .setView(container)
            .setPositiveButton("Confirmar") { _, _ ->
                val qtyStr = input.text.toString()
                val qty = qtyStr.toIntOrNull()
                
                if (qty != null && qty > 0 && qty <= pendingQty) {
                    processQuantityInput(item, qty)
                } else {
                    Toast.makeText(requireContext(), "Cantidad inválida. Debe ser entre 1 y $pendingQty.", Toast.LENGTH_LONG).show()
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun processQuantityInput(item: com.smartwms.operario.data.api.WorkOrderItem, qtyToAdd: Int) {
        val success = orderVm.addSkuPicked(item.sku, item.quantity, qtyToAdd)
        if (!success) {
            Toast.makeText(requireContext(), "Error al registrar la cantidad.", Toast.LENGTH_SHORT).show()
            return
        }

        if (orderVm.isPickingComplete()) {
            Toast.makeText(requireContext(), "✅ Picking completado", Toast.LENGTH_SHORT).show()
            // Automáticamente salir de Picking e ir a Cerrar pedido
            findNavController().popBackStack(R.id.homeFragment, false)
            findNavController().navigate(R.id.packingFragment)
        } else {
            val currentQty = (orderVm.pickedSkus.value?.get(item.sku) ?: 0)
            Toast.makeText(requireContext(), "✓ ${item.productName} ($currentQty / ${item.quantity})", Toast.LENGTH_SHORT).show()
        }
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
        _binding = null
    }
}
