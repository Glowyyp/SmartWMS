// ui/fragments/PutawayFragment.kt
// Formulario de Putaway — Almacenar producto en ubicacion

package com.smartwms.operario.ui.fragments

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.fragment.app.Fragment
import com.smartwms.operario.databinding.FragmentPutawayBinding

class PutawayFragment : Fragment() {

    private var _binding: FragmentPutawayBinding? = null
    private val binding get() = _binding!!

    private val validLocations = listOf(
        "A-01-A","A-01-B","A-02-A","A-03-B",
        "B-01-A","B-02-C","C-01-A","C-02-B",
        "C-03-B","D-01-A"
    )

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentPutawayBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        // Poblar spinner de ubicaciones
        val adapter = ArrayAdapter(requireContext(),
            android.R.layout.simple_spinner_item, validLocations)
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        binding.spinnerLocation.adapter = adapter

        binding.btnConfirmPutaway.setOnClickListener {
            val sku      = binding.etSku.text.toString().trim()
            val qtyStr   = binding.etQuantity.text.toString().trim()
            val location = binding.spinnerLocation.selectedItem as? String ?: ""

            if (sku.isEmpty()) {
                binding.etSku.error = "El SKU es requerido"
                return@setOnClickListener
            }
            val qty = qtyStr.toIntOrNull()
            if (qty == null || qty < 1) {
                binding.etQuantity.error = "Cantidad invalida"
                return@setOnClickListener
            }
            if (location.isEmpty()) {
                Toast.makeText(requireContext(), "Selecciona una ubicacion", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            // Confirmacion exitosa
            Toast.makeText(requireContext(), "Almacenado: $sku x$qty → $location", Toast.LENGTH_LONG).show()
            binding.etSku.text?.clear()
            binding.etQuantity.text?.clear()
            binding.spinnerLocation.setSelection(0)
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
