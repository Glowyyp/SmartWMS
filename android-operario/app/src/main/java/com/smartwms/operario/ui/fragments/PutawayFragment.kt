// ui/fragments/PutawayFragment.kt
// Módulo Putaway conectado en tiempo real al Layout del Supervisor e Inventario:
// autocompletado de SKU, escáner, almacenamiento inicial o traslado entre ubicaciones.

package com.smartwms.operario.ui.fragments

import android.app.AlertDialog
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.AdapterView
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

    private data class SourceOption(
        val code: String?, // null = Stock sin ubicar
        val label: String,
        val maxQuantity: Int
    )

    private var _binding: FragmentPutawayBinding? = null
    private val binding get() = _binding!!

    private val orderVm: OrderViewModel by activityViewModels()

    private lateinit var skuAdapter: SkuAutocompleteAdapter
    private var inventoryBySku: Map<String, Product> = emptyMap()
    private var selectedProduct: Product? = null
    private var locationItems: List<WarehouseLocationItem> = emptyList()
    private var sourceOptions: List<SourceOption> = emptyList()

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
        setupSourceSpinnerListener()
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

    override fun onResume() {
        super.onResume()
        // Garantiza que ubicaciones creadas/eliminadas en Supervisor aparezcan al volver
        orderVm.refreshInventory()
    }

    private fun setupSkuAutocomplete() {
        skuAdapter = SkuAutocompleteAdapter(requireContext(), emptyList())
        binding.actvSku.setAdapter(skuAdapter)
        binding.actvSku.threshold = 0

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
                    sourceOptions = emptyList()
                    binding.cardSelectedProduct.visibility = View.GONE
                    binding.containerSourceLocation.visibility = View.GONE
                }
            }
        })
    }

    private fun setupSourceSpinnerListener() {
        binding.spinnerSourceLocation.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val opt = sourceOptions.getOrNull(position) ?: return
                binding.tilQuantity.error = null
                binding.tilQuantity.hint = "Cantidad a almacenar (máx ${opt.maxQuantity}) *"
                if (opt.maxQuantity > 0 && binding.etQuantity.text.isNullOrBlank()) {
                    binding.etQuantity.setText(opt.maxQuantity.toString())
                }
            }

            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
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
            setupLocationsSpinner(locs ?: emptyList())
        }

        orderVm.isLoading.observe(viewLifecycleOwner) { loading ->
            binding.pbPutaway.visibility = if (loading) View.VISIBLE else View.GONE
            binding.btnConfirmPutaway.isEnabled = !loading
        }
    }

    private fun setupLocationsSpinner(items: List<WarehouseLocationItem>) {
        locationItems = items
        val labels = if (items.isEmpty()) {
            listOf("Cargando ubicaciones del Layout...")
        } else {
            items.map { item ->
                val occ = if (item.isOccupied) " [${item.totalUnits} uds]" else " [Vacía]"
                "${item.code} · ${item.label}$occ"
            }
        }
        val adapter = ArrayAdapter(requireContext(), android.R.layout.simple_spinner_item, labels)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        binding.spinnerLocation.adapter = adapter
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

        val locDesc = if (product.locationStocks.isNotEmpty()) {
            val parts = product.locationStocks.joinToString(", ") { "${it.locationCode}: ${it.quantity} uds" }
            if (product.unlocatedQty > 0) "$parts · Sin ubicar: ${product.unlocatedQty} uds" else parts
        } else {
            "Sin ubicar (${product.unlocatedQty} uds disponibles para almacenar)"
        }
        binding.tvSelectedCurrentLoc.text = "Distribución actual: $locDesc"

        populateSourceOptions(product)
    }

    private fun populateSourceOptions(product: Product) {
        val opts = mutableListOf<SourceOption>()
        if (product.unlocatedQty > 0) {
            opts.add(
                SourceOption(
                    code = null,
                    label = "Stock sin ubicar (${product.unlocatedQty} uds disponibles)",
                    maxQuantity = product.unlocatedQty
                )
            )
        }
        for (loc in product.locationStocks) {
            if (loc.quantity > 0) {
                opts.add(
                    SourceOption(
                        code = loc.locationCode,
                        label = "Mover desde ${loc.locationCode} — ${loc.locationName} (${loc.quantity} uds)",
                        maxQuantity = loc.quantity
                    )
                )
            }
        }
        sourceOptions = opts

        if (opts.isEmpty()) {
            binding.containerSourceLocation.visibility = View.GONE
            binding.tilQuantity.hint = "Cantidad a almacenar *"
        } else {
            binding.containerSourceLocation.visibility = View.VISIBLE
            val adapter = ArrayAdapter(requireContext(), android.R.layout.simple_spinner_item, opts.map { it.label })
            adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
            binding.spinnerSourceLocation.adapter = adapter
            binding.etQuantity.setText(opts.first().maxQuantity.toString())
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

        if (product.stockQuantity <= 0 || sourceOptions.isEmpty()) {
            binding.tilQuantity.error = "Sin stock disponible para ubicar"
            AlertDialog.Builder(requireContext())
                .setTitle("⚠️ Sin stock físico disponible")
                .setMessage(
                    "El producto ${product.sku} (${product.productName}) no tiene stock físico disponible para ubicar."
                )
                .setPositiveButton("OK", null)
                .show()
            return
        }

        val sourceOpt = sourceOptions.getOrNull(binding.spinnerSourceLocation.selectedItemPosition)
        if (sourceOpt == null) {
            Toast.makeText(requireContext(), "Selecciona el origen del stock", Toast.LENGTH_SHORT).show()
            return
        }

        val qtyStr = binding.etQuantity.text?.toString()?.trim().orEmpty()
        val qty = qtyStr.toIntOrNull()
        if (qty == null || qty < 1) {
            binding.tilQuantity.error = "Ingresa una cantidad mayor a 0"
            return
        }
        if (qty > sourceOpt.maxQuantity) {
            binding.tilQuantity.error = "Máximo permitido desde este origen: ${sourceOpt.maxQuantity} uds"
            AlertDialog.Builder(requireContext())
                .setTitle("⚠️ Cantidad supera disponibilidad")
                .setMessage(
                    "Intentas ubicar $qty unidades de ${product.sku}, pero el origen seleccionado solo dispone de ${sourceOpt.maxQuantity} unidades."
                )
                .setPositiveButton("OK", null)
                .show()
            return
        }
        binding.tilQuantity.error = null

        val targetLoc = locationItems.getOrNull(binding.spinnerLocation.selectedItemPosition)
        if (targetLoc == null) {
            Toast.makeText(requireContext(), "No hay ubicaciones cargadas desde el Layout", Toast.LENGTH_SHORT).show()
            orderVm.refreshInventory()
            return
        }

        if (sourceOpt.code != null && sourceOpt.code.equals(targetLoc.code, ignoreCase = true)) {
            AlertDialog.Builder(requireContext())
                .setTitle("⚠️ Ubicación repetida")
                .setMessage("El producto ya está en ${targetLoc.code}. Selecciona una ubicación de destino diferente para trasladarlo.")
                .setPositiveButton("OK", null)
                .show()
            return
        }

        orderVm.registerPutaway(
            sku = product.sku,
            quantity = qty,
            location = targetLoc.code,
            sourceLocation = sourceOpt.code,
            notes = null,
            onSuccess = { res ->
                if (_binding == null) return@registerPutaway
                val origenText = res.sourceLocation ?: "Stock sin ubicar"
                AlertDialog.Builder(requireContext())
                    .setTitle("✅ Almacenamiento Registrado")
                    .setMessage(
                        "Producto: ${res.productName} (${res.sku})\n" +
                        "Cantidad: ${res.quantity} uds\n" +
                        "Movimiento: $origenText → ${res.newLocation}\n" +
                        "Total en ${res.newLocation}: ${res.locationTotalQuantity} uds\n" +
                        "Stock físico total: ${res.stockQuantity} uds"
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
        sourceOptions = emptyList()
        binding.actvSku.setText("", false)
        binding.etQuantity.text?.clear()
        binding.tilSku.error = null
        binding.tilQuantity.error = null
        binding.tilQuantity.hint = "Cantidad a almacenar *"
        binding.cardSelectedProduct.visibility = View.GONE
        binding.containerSourceLocation.visibility = View.GONE
        if (locationItems.isNotEmpty()) {
            binding.spinnerLocation.setSelection(0)
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
