// ui/fragments/PackingFragment.kt
// Verificacion de la lista de items empacados antes del despacho.
// Usa el selectedOrder del OrderViewModel para mostrar el estado del pedido activo.

package com.smartwms.operario.ui.fragments

import android.graphics.Color
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.navigation.fragment.findNavController
import com.smartwms.operario.R
import com.smartwms.operario.databinding.FragmentPackingBinding
import com.smartwms.operario.ui.OrderViewModel
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.journeyapps.barcodescanner.ScanIntentResult
import android.app.AlertDialog

class PackingFragment : Fragment() {

    private var _binding: FragmentPackingBinding? = null
    private val binding get() = _binding!!

    // Mismo ViewModel que PickingFragment — comparten el mismo estado
    private val orderVm: OrderViewModel by activityViewModels()

    // Launcher para el escáner QR de ZXing
    private val qrLauncher = registerForActivityResult(ScanContract()) { result: ScanIntentResult ->
        if (result.contents != null) {
            handleQrScan(result.contents)
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentPackingBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Observar el pedido seleccionado para actualizar la vista
        orderVm.selectedOrder.observe(viewLifecycleOwner) { order ->
            renderPackingState(order)
        }

        // Observar resultado del despacho
        orderVm.dispatchResult.observe(viewLifecycleOwner) { dispatched ->
            if (dispatched != null) {
                binding.btnClosePacking.isEnabled = false
                binding.btnClosePacking.text = "✅ Orden Despachada"
                Toast.makeText(requireContext(), "✓ Pedido ${dispatched.orderNumber} finalizado correctamente", Toast.LENGTH_LONG).show()
                orderVm.clearDispatchResult()
                orderVm.clearSelectedOrder()
                
                // Volver a Inicio
                findNavController().popBackStack(R.id.homeFragment, false)
            }
        }

        binding.btnClosePacking.setOnClickListener {
            val order = orderVm.selectedOrder.value
            if (order != null && order.status == "pending") {
                val options = ScanOptions()
                options.setDesiredBarcodeFormats(ScanOptions.ALL_CODE_TYPES)
                options.setPrompt("Escanea el QR de la Mesa")
                options.setCameraId(0)
                options.setBeepEnabled(true)
                options.setBarcodeImageEnabled(false)
                options.setOrientationLocked(false)
                qrLauncher.launch(options)
            } else {
                Toast.makeText(requireContext(), "No hay pedido pendiente para cerrar.", Toast.LENGTH_SHORT).show()
            }
        }

        // Renderizar estado inicial
        renderPackingState(orderVm.selectedOrder.value)
    }

    private fun renderPackingState(order: com.smartwms.operario.data.api.WorkOrder?) {
        if (order == null) {
            binding.tvPackingStatus.text = "⚠️ No hay pedido seleccionado.\n\nVe a la pestaña Picking y selecciona un pedido."
            binding.tvPackingStatus.setTextColor(Color.parseColor("#facc15"))
            binding.btnClosePacking.isEnabled = false
            binding.llItemsSummary.removeAllViews()
            return
        }

        val statusLabel = when (order.status) {
            "dispatched" -> {
                binding.tvPackingStatus.setTextColor(Color.parseColor("#4ade80"))
                binding.btnClosePacking.isEnabled = false
                binding.btnClosePacking.text = "✅ Pedido Despachado"
                "✅ Pedido ${order.orderNumber} ya fue despachado."
            }
            "cancelled" -> {
                binding.tvPackingStatus.setTextColor(Color.parseColor("#f87171"))
                binding.btnClosePacking.isEnabled = false
                "❌ Pedido ${order.orderNumber} está cancelado."
            }
            else -> {
                binding.tvPackingStatus.setTextColor(Color.parseColor("#4ade80"))
                binding.btnClosePacking.isEnabled = true
                binding.btnClosePacking.text = "📷 Escanear QR de Mesa"
                "📋 Pedido ${order.orderNumber} — Todos los productos recolectados.\n\nEscanea la mesa para finalizar."
            }
        }
        binding.tvPackingStatus.text = statusLabel

        // Renderizar lista de items del pedido
        renderItemsList(order)
    }

    private fun renderItemsList(order: com.smartwms.operario.data.api.WorkOrder) {
        binding.llItemsSummary.removeAllViews()

        order.items.forEach { item ->
            val row = layoutInflater.inflate(
                android.R.layout.simple_list_item_2,
                binding.llItemsSummary,
                false
            )
            val text1 = row.findViewById<android.widget.TextView>(android.R.id.text1)
            val text2 = row.findViewById<android.widget.TextView>(android.R.id.text2)

            // En packing mostramos todos los items del pedido con la ubicacion de inventario
            val location = orderVm.getSkuLocation(item.sku) ?: "—"
            text1.text = "📦 ${item.productName} ×${item.quantity}"
            text1.setTextColor(Color.parseColor("#e2e8f0"))
            text2.text = "SKU: ${item.sku}  |  📍 Zona: $location"
            text2.setTextColor(Color.parseColor("#9ca3af"))

            binding.llItemsSummary.addView(row)
        }
    }

    private fun handleQrScan(scannedCode: String) {
        val order = orderVm.selectedOrder.value ?: return
        val expectedCode = "MESA-${order.orderNumber}"
        
        if (scannedCode.trim().equals(expectedCode, ignoreCase = true)) {
            // Mesa válida
            Toast.makeText(requireContext(), "Mesa válida. Finalizando pedido...", Toast.LENGTH_SHORT).show()
            orderVm.dispatchSelectedOrder()
        } else {
            // Mesa inválida
            AlertDialog.Builder(requireContext())
                .setTitle("❌ Mesa Incorrecta")
                .setMessage("Esta mesa no corresponde al pedido.\n\nCódigo escaneado: $scannedCode\nEsperado: $expectedCode")
                .setPositiveButton("OK", null)
                .show()
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
