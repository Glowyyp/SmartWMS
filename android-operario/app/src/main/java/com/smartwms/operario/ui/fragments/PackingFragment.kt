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
import android.widget.EditText
import android.widget.FrameLayout
import android.text.InputType

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

        // Botón volver en la barra superior
        binding.btnBackPacking.setOnClickListener {
            navigateBackSafely()
        }

        // Observar el pedido seleccionado para actualizar la vista
        orderVm.selectedOrder.observe(viewLifecycleOwner) { order ->
            renderPackingState(order)
        }

        // Observar resultado del despacho
        orderVm.dispatchResult.observe(viewLifecycleOwner) { dispatched ->
            if (dispatched != null) {
                binding.btnClosePacking.isEnabled = true
                binding.btnClosePacking.text = "✅ Pedido Despachado (Volver al Inicio)"
                binding.btnClosePacking.setOnClickListener {
                    orderVm.clearDispatchResult()
                    orderVm.clearSelectedOrder()
                    navigateBackSafely()
                }

                AlertDialog.Builder(requireContext())
                    .setTitle("✅ Pedido Finalizado")
                    .setMessage("El pedido ${dispatched.orderNumber} ha sido completado y despachado exitosamente.\n\nEl stock físico ha sido descontado.")
                    .setCancelable(false)
                    .setPositiveButton("Volver al Inicio") { _, _ ->
                        orderVm.clearDispatchResult()
                        orderVm.clearSelectedOrder()
                        navigateBackSafely()
                    }
                    .show()
            }
        }

        orderVm.error.observe(viewLifecycleOwner) { errMsg ->
            if (errMsg != null) {
                AlertDialog.Builder(requireContext())
                    .setTitle("Error al Despachar")
                    .setMessage(errMsg)
                    .setPositiveButton("OK", null)
                    .show()
                orderVm.clearError()
            }
        }

        binding.btnClosePacking.setOnClickListener {
            val order = orderVm.selectedOrder.value
            if (order != null && (order.status == "pending" || order.status == "assigned")) {
                val options = ScanOptions().apply {
                    setDesiredBarcodeFormats(ScanOptions.ALL_CODE_TYPES)
                    setPrompt("Escanea el código de la Mesa (QR o Barras)")
                    setCameraId(0)
                    setBeepEnabled(true)
                    setBarcodeImageEnabled(false)
                    setOrientationLocked(false)
                }
                qrLauncher.launch(options)
            } else if (order != null && order.status == "dispatched") {
                navigateBackSafely()
            } else {
                Toast.makeText(requireContext(), "No hay pedido pendiente para cerrar.", Toast.LENGTH_SHORT).show()
            }
        }

        binding.btnManualPacking.setOnClickListener {
            val order = orderVm.selectedOrder.value
            if (order != null && (order.status == "pending" || order.status == "assigned")) {
                showManualTableDialog()
            } else {
                Toast.makeText(requireContext(), "No hay pedido pendiente para cerrar.", Toast.LENGTH_SHORT).show()
            }
        }

        // Renderizar estado inicial
        renderPackingState(orderVm.selectedOrder.value)
    }

    private fun navigateBackSafely() {
        orderVm.clearSelectedOrder()
        if (!findNavController().popBackStack(R.id.homeFragment, false)) {
            if (!findNavController().popBackStack()) {
                findNavController().navigate(R.id.homeFragment)
            }
        }
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
                binding.btnClosePacking.isEnabled = true
                binding.btnManualPacking.isEnabled = false
                binding.btnManualPacking.visibility = View.GONE
                binding.btnClosePacking.text = "✅ Pedido Despachado (Volver al Inicio)"
                binding.btnClosePacking.setOnClickListener {
                    navigateBackSafely()
                }
                "✅ Pedido ${order.orderNumber} ya fue despachado."
            }
            "cancelled" -> {
                binding.tvPackingStatus.setTextColor(Color.parseColor("#f87171"))
                binding.btnClosePacking.isEnabled = false
                binding.btnManualPacking.isEnabled = false
                "❌ Pedido ${order.orderNumber} está cancelado."
            }
            else -> {
                binding.tvPackingStatus.setTextColor(Color.parseColor("#4ade80"))
                binding.btnClosePacking.isEnabled = true
                binding.btnManualPacking.isEnabled = true
                binding.btnManualPacking.visibility = View.VISIBLE
                binding.btnClosePacking.text = "📷 Escanear Mesa"
                "📋 Pedido ${order.orderNumber} — Todos los productos recolectados.\n\nEscanea o ingresa la mesa para finalizar."
            }
        }
        binding.tvPackingStatus.text = statusLabel

        // Renderizar lista de items del pedido con pesos y volumen estimado
        renderItemsList(order)
    }

    private fun renderItemsList(order: com.smartwms.operario.data.api.WorkOrder) {
        binding.llItemsSummary.removeAllViews()

        var totalEstWeight = 0.0
        var totalEstVolume = 0.0
        var hasEstimates = false

        order.items.forEach { item ->
            val row = layoutInflater.inflate(
                android.R.layout.simple_list_item_2,
                binding.llItemsSummary,
                false
            )
            val text1 = row.findViewById<android.widget.TextView>(android.R.id.text1)
            val text2 = row.findViewById<android.widget.TextView>(android.R.id.text2)

            val location = orderVm.getSkuLocation(item.sku) ?: "—"
            val weight = orderVm.getSkuWeight(item.sku)
            val volume = orderVm.getSkuVolume(item.sku)

            if (weight != null) {
                totalEstWeight += weight * item.quantity
                hasEstimates = true
            }
            if (volume != null) {
                totalEstVolume += volume * item.quantity
                hasEstimates = true
            }

            val weightStr = if (weight != null) " | ⚖️ ${(weight * item.quantity)} kg" else ""
            val volStr = if (volume != null) " | 📐 ${(volume * item.quantity).toInt()} cm³" else ""

            text1.text = "📦 ${item.productName} ×${item.quantity}"
            text1.setTextColor(Color.parseColor("#e2e8f0"))
            text2.text = "SKU: ${item.sku}  |  📍 Zona: $location$weightStr$volStr"
            text2.setTextColor(Color.parseColor("#9ca3af"))

            binding.llItemsSummary.addView(row)
        }

        // Pre-rellenar peso estimado si el usuario aún no lo ha ingresado
        if (hasEstimates && totalEstWeight > 0 && binding.etPkgWeight.text.isNullOrBlank()) {
            binding.etPkgWeight.setText(String.format(java.util.Locale.US, "%.2f", totalEstWeight))
        }
    }

    private fun showManualTableDialog() {
        val order = orderVm.selectedOrder.value ?: return
        val expectedCode = "MESA-${order.orderNumber}"
        val input = EditText(requireContext()).apply {
            hint = "Ej: $expectedCode"
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
            .setTitle("⌨️ Ingreso Manual de Mesa")
            .setMessage("Ingresa el identificador de la mesa de empaque asignada:")
            .setView(container)
            .setPositiveButton("Confirmar Mesa") { _, _ ->
                val code = input.text.toString().trim()
                if (code.isNotEmpty()) {
                    processTableCode(code)
                } else {
                    Toast.makeText(requireContext(), "Debes ingresar un código de mesa.", Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun handleQrScan(scannedCode: String) {
        processTableCode(scannedCode)
    }

    private fun processTableCode(code: String) {
        val order = orderVm.selectedOrder.value ?: return
        val expectedCode = "MESA-${order.orderNumber}"
        val clean = code.trim()

        if (clean.equals(expectedCode, ignoreCase = true) || clean.equals(order.orderNumber, ignoreCase = true)) {
            // Leer valores de los bultos
            val l = binding.etPkgLength.text.toString().toDoubleOrNull()
            val w = binding.etPkgWidth.text.toString().toDoubleOrNull()
            val h = binding.etPkgHeight.text.toString().toDoubleOrNull()
            val weight = binding.etPkgWeight.text.toString().toDoubleOrNull()

            val pkgList = if (l != null || w != null || h != null || weight != null) {
                listOf(com.smartwms.operario.data.api.DispatchPackageIn(
                    length = l, width = w, height = h, weight = weight
                ))
            } else emptyList()

            val payload = com.smartwms.operario.data.api.DispatchIn(
                packages = pkgList,
                totalWeight = weight,
                totalVolume = if (l != null && w != null && h != null) (l * w * h) else null
            )

            Toast.makeText(requireContext(), "✓ Mesa verificada. Finalizando despacho...", Toast.LENGTH_SHORT).show()
            orderVm.dispatchSelectedOrder(payload)
        } else {
            AlertDialog.Builder(requireContext())
                .setTitle("❌ Mesa Incorrecta")
                .setMessage("El código ingresado o escaneado no corresponde a la mesa de este pedido.\n\nCódigo recibido: $clean\nEsperado: $expectedCode")
                .setPositiveButton("OK", null)
                .show()
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
