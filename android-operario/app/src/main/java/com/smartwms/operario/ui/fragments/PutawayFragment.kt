// ui/fragments/PutawayFragment.kt
// Módulo Putaway conectado al inventario real: autocompletado de SKU, escáner,
// validación de existencia/stock/ubicación y persistencia en backend.

package com.smartwms.operario.ui.fragments

import android.app.AlertDialog
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanIntentResult
import com.smartwms.operario.R
import com.smartwms.operario.data.api.Product
import com.smartwms.operario.data.api.WarehouseLocationItem
import com.smartwms.operario.databinding.FragmentPutawayBinding
import com.smartwms.operario.ui.OrderViewModel
import com.smartwms.operario.ui.SmartCaptureActivity
import com.smartwms.operario.ui.adapters.SkuAutocompleteAdapter

class PutawayFragment : Fragment() {

    private var _binding: FragmentPutawayBinding? = null
    private val binding get() = _binding!!

    private val orderVm: OrderViewModel by activityViewModels()

    private lateinit var skuAdapter: SkuAutocompleteAdapter
    private var inventoryBySku: Map<String, Product> = emptyMap()
    private var selectedProduct: Product? = null

    private val defaultLocations = listOf(
        WarehouseLocationItem("A-01", "A", "Zona A — Insumos (Rack A-01)"),
        WarehouseLocationItem("A-02", "A", "Zona A — Insumos (Rack A-02)"),
        WarehouseLocationItem("A-03", "A", "Zona A — Insumos (Rack A-03)"),
        WarehouseLocationItem("B-01", "B", "Zona B — Electrónica (Rack B-01)"),
        WarehouseLocationItem("B-02", "B", "Zona B — Electrónica (Rack B-02)"),
        WarehouseLocationItem("B-03", "B", "Zona B — Electrónica (Rack B-03)"),
        WarehouseLocationItem("B-04", "B", "Zona B — Electrónica (Rack B-04)"),
        WarehouseLocationItem("C-01", "C", "Zona C — Periféricos (Rack C-01)"),
        WarehouseLocationItem("C-02", "C", "Zona C — Periféricos (Rack C-02)"),
        WarehouseLocationItem("C-03", "C", "Zona C — Periféricos (Rack C-03)"),
        WarehouseLocationItem("D-01", "D", "Zona D — Cuarentena (Rack D-01)"),
        WarehouseLocationItem("D-02", "D", "Zona D — Cuarentena (Rack D-02)")
    )
    private var locationItems: List<WarehouseLocationItem> = defaultLocations

    private val scanSkuLauncher = registerForActivityResult(ScanContract()) { result: ScanIntentResult ->
        val scanned = result.contents?.trim()
        if (!scanned.isNullOrEmpty()) {
            applyScannedOrTypedSku(scanned)
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentPutawayBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        setupSkuAutocomplete()
        setupLocationsSpinner(defaultLocations)
        observeViewModel()
        orderVm.refreshInventory()

        binding.btnScanPutawaySku.setOnClickListener {
            scanSkuLauncher.launch(
                SmartCaptureActivity.buildScanOptions("Escanea el código del producto (QR o Barras)")
            )
        }

        binding.btnConfirmPutaway.setOnClickListener {
            submitPutaway()
        }
    }

    private fun setupSkuAutocomplete() {
        skuAdapter = SkuAutocompleteAdapter(requireContext(), emptyList())
        binding.actvSku.setAdapter(skuAdapter)
        binding.actvSku.threshold = 0

        // Mostrar desplegable inmediatamente al tocar o enfocar el campo SKU
        binding.actvSku.setOnClickListener {
            skuAdapter.filter.filter(binding.actvSku.text) {
                if (_binding != null) binding.actvSku.showDropDown()
            }
        }
        binding.actvSku.setOnFocusChangeListener { _, hasFocus ->
            if (hasFocus && _binding != null) {
                skuAdapter.filter.filter(binding.actvSku.text) {
                    if (_binding != null && binding.actvSku.hasFocus()) {
                        binding.actvSku.showDropDown()
                    }
                }
            }
        }

        binding.actvSku.setOnItemClickListener { _, _, position, _ ->
            val picked = skuAdapter.getItem(position) ?: return@setOnItemClickListener
            onProductSelected(picked, updateText = true)
        }

        binding.actvSku.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                binding.tilSku.error = null
            }

            override fun afterTextChanged(s: Editable?) {
                val typed = s?.toString()?.trim().orEmpty()
                val match = findProductBySku(typed)
                if (match != null) {
                    onProductSelected(match, updateText = false)
                } else {
                    selectedProduct = null
                    binding.cardSelectedProduct.visibility = View.GONE
                }
            }
        })
    }

    private fun observeViewModel() {
        orderVm.inventoryMap.observe(viewLifecycleOwner) { map ->
            inventoryBySku = map
            skuAdapter.updateProducts(map.values.toList())
            val currentSku = binding.actvSku.text?.toString()?.trim().orEmpty()
            if (currentSku.isNotEmpty()) {
                findProductBySku(currentSku)?.let { onProductSelected(it, updateText = false) }
            }
        }

        orderVm.warehouseLocations.observe(viewLifecycleOwner) { locs ->
            if (!locs.isNullOrEmpty()) {
                setupLocationsSpinner(locs)
            }
        }

        orderVm.isLoading.observe(viewLifecycleOwner) { loading ->
            binding.pbPutaway.visibility = if (loading) View.VISIBLE else View.GONE
            binding.btnConfirmPutaway.isEnabled = !loading
        }
    }

    private fun setupLocationsSpinner(items: List<WarehouseLocationItem>) {
        locationItems = items
        val labels = items.map { "${it.code} · ${it.label}" }
        val adapter = ArrayAdapter(requireContext(), android.R.layout.simple_spinner_item, labels)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        binding.spinnerLocation.adapter = adapter
        selectedProduct?.let { selectCurrentLocationInSpinner(it.warehouseLocation) }
    }

    private fun findProductBySku(rawSku: String): Product? {
        if (rawSku.isBlank()) return null
        return inventoryBySku[rawSku]
            ?: inventoryBySku.values.firstOrNull { it.sku.equals(rawSku, ignoreCase = true) }
    }

    private fun applyScannedOrTypedSku(code: String) {
        val product = findProductBySku(code)
        if (product == null) {
            AlertDialog.Builder(requireContext())
                .setTitle("❌ SKU no encontrado")
                .setMessage("El código escaneado '$code' no corresponde a ningún producto registrado en el inventario.")
                .setPositiveButton("OK", null)
                .show()
            return
        }
        onProductSelected(product, updateText = true)
    }

    private fun onProductSelected(product: Product, updateText: Boolean) {
        selectedProduct = product
        binding.tilSku.error = null
        if (updateText && binding.actvSku.text.toString() != product.sku) {
            binding.actvSku.setText(product.sku, false)
            binding.actvSku.setSelection(product.sku.length)
        }

        binding.cardSelectedProduct.visibility = View.VISIBLE
        binding.tvSelectedName.text = product.productName
        binding.tvSelectedSku.text = "SKU: ${product.sku}"

        val hasStock = product.stockQuantity > 0
        binding.tvSelectedStock.text = if (hasStock) {
            "Stock físico: ${product.stockQuantity} uds  |  Disponible: ${product.availableQty} uds"
        } else {
            "Sin stock físico (0 uds) — Confirma una recepción antes de ubicar"
        }
        binding.tvSelectedStock.setTextColor(
            ContextCompat.getColor(
                requireContext(),
                if (hasStock) R.color.green_accent else R.color.error_color
            )
        )

        val currentLoc = product.warehouseLocation?.takeIf { it.isNotBlank() } ?: "Sin asignar"
        binding.tvSelectedCurrentLoc.text = "Ubicación actual: $currentLoc"

        selectCurrentLocationInSpinner(product.warehouseLocation)

        if (hasStock && binding.etQuantity.text.isNullOrBlank()) {
            binding.etQuantity.setText(product.stockQuantity.toString())
        }
    }

    private fun selectCurrentLocationInSpinner(currentLocation: String?) {
        if (currentLocation.isNullOrBlank()) return
        val idx = locationItems.indexOfFirst { it.code.equals(currentLocation.trim(), ignoreCase = true) }
        if (idx >= 0) {
            binding.spinnerLocation.setSelection(idx)
        }
    }

    private fun submitPutaway() {
        val rawSku = binding.actvSku.text?.toString()?.trim().orEmpty()
        if (rawSku.isEmpty()) {
            binding.tilSku.error = "Selecciona o ingresa un SKU"
            return
        }

        val product = findProductBySku(rawSku)
        if (product == null) {
            binding.tilSku.error = "El SKU '$rawSku' no existe en inventario"
            AlertDialog.Builder(requireContext())
                .setTitle("❌ SKU inválido")
                .setMessage("El SKU '$rawSku' no corresponde a un producto válido en el inventario. Selecciónalo desde la lista desplegable.")
                .setPositiveButton("OK", null)
                .show()
            return
        }

        if (product.stockQuantity <= 0) {
            binding.tilQuantity.error = "Sin stock físico en bodega"
            AlertDialog.Builder(requireContext())
                .setTitle("⚠️ Sin stock físico")
                .setMessage(
                    "El producto ${product.sku} (${product.productName}) tiene stock físico = 0.\n\n" +
                    "Solo se puede hacer Putaway de productos con stock recibido en bodega."
                )
                .setPositiveButton("OK", null)
                .show()
            return
        }

        val qtyStr = binding.etQuantity.text?.toString()?.trim().orEmpty()
        val qty = qtyStr.toIntOrNull()
        if (qty == null || qty < 1) {
            binding.tilQuantity.error = "Ingresa una cantidad mayor a 0"
            return
        }
        if (qty > product.stockQuantity) {
            binding.tilQuantity.error = "Máximo permitido: ${product.stockQuantity} uds"
            AlertDialog.Builder(requireContext())
                .setTitle("⚠️ Cantidad supera el stock")
                .setMessage(
                    "Intentas ubicar $qty unidades de ${product.sku}, pero solo hay ${product.stockQuantity} unidades físicas en bodega."
                )
                .setPositiveButton("OK", null)
                .show()
            return
        }
        binding.tilQuantity.error = null

        val pos = binding.spinnerLocation.selectedItemPosition
        val targetLoc = locationItems.getOrNull(pos)
        if (targetLoc == null) {
            Toast.makeText(requireContext(), "Selecciona una ubicación válida", Toast.LENGTH_SHORT).show()
            return
        }

        orderVm.registerPutaway(
            sku = product.sku,
            quantity = qty,
            location = targetLoc.code,
            onSuccess = { res ->
                if (_binding == null) return@registerPutaway
                val prev = res.previousLocation?.takeIf { it.isNotBlank() } ?: "Sin asignar"
                AlertDialog.Builder(requireContext())
                    .setTitle("✅ Almacenamiento Registrado")
                    .setMessage(
                        "Producto: ${res.productName} (${res.sku})\n" +
                        "Cantidad ubicada: ${res.quantity} uds\n" +
                        "Ubicación: $prev → ${res.newLocation}\n" +
                        "Stock físico actual: ${res.stockQuantity} uds"
                    )
                    .setPositiveButton("Aceptar", null)
                    .show()
                resetForm()
            },
            onError = { errMsg ->
                if (_binding == null) return@registerPutaway
                AlertDialog.Builder(requireContext())
                    .setTitle("❌ Error en Putaway")
                    .setMessage(errMsg)
                    .setPositiveButton("OK", null)
                    .show()
            }
        )
    }

    private fun resetForm() {
        selectedProduct = null
        binding.actvSku.setText("", false)
        binding.etQuantity.text?.clear()
        binding.tilSku.error = null
        binding.tilQuantity.error = null
        binding.cardSelectedProduct.visibility = View.GONE
        binding.spinnerLocation.setSelection(0)
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
