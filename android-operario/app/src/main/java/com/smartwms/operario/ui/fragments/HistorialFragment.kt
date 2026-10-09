// ui/fragments/HistorialFragment.kt
// Historial completo de pedidos del operario (dispatched + cancelled).
// Carga desde la API real filtrando por el email del operario logueado.

package com.smartwms.operario.ui.fragments

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.AdapterView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.navigation.fragment.findNavController
import com.smartwms.operario.R
import com.smartwms.operario.data.api.WorkOrder
import com.smartwms.operario.databinding.FragmentHistorialBinding
import com.smartwms.operario.ui.OrderViewModel
import com.smartwms.operario.ui.adapters.WorkOrderAdapter

class HistorialFragment : Fragment() {

    private var _binding: FragmentHistorialBinding? = null
    private val binding get() = _binding!!

    private val orderVm: OrderViewModel by activityViewModels()
    private lateinit var historialAdapter: WorkOrderAdapter
    private var currentFilter = "all"   // "all" | "dispatched" | "cancelled"

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentHistorialBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        setupRecyclerView()
        setupFilterSpinner()
        setupRefreshButton()
        observeViewModel()
    }

    private fun setupRecyclerView() {
        historialAdapter = WorkOrderAdapter(emptyList()) { order ->
            // Al tocar un pedido del historial → navegar a la pantalla de detalle
            val bundle = Bundle().apply {
                putInt("orderId", order.id)
            }
            findNavController().navigate(R.id.orderDetailFragment, bundle)
        }
        binding.rvHistorial.layoutManager = LinearLayoutManager(requireContext())
        binding.rvHistorial.adapter = historialAdapter
    }

    private fun setupFilterSpinner() {
        val options = listOf("Todos los estados", "Despachados", "Cancelados")
        val adapter = ArrayAdapter(
            requireContext(),
            android.R.layout.simple_spinner_item,
            options
        )
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        binding.spinnerFilter.adapter = adapter

        binding.spinnerFilter.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                currentFilter = when (pos) {
                    1 -> "dispatched"
                    2 -> "cancelled"
                    else -> "all"
                }
                applyFilter()
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
    }

    private fun setupRefreshButton() {
        binding.btnRefreshHistorial.setOnClickListener {
            orderVm.loadAllOrders()
        }
    }

    private fun observeViewModel() {
        orderVm.allOrders.observe(viewLifecycleOwner) { orders ->
            applyFilter(orders)
        }

        orderVm.isLoading.observe(viewLifecycleOwner) { loading ->
            binding.progressHistorial.visibility = if (loading) View.VISIBLE else View.GONE
        }

        orderVm.error.observe(viewLifecycleOwner) { error ->
            if (error != null) {
                binding.tvHistorialError.text = error
                binding.tvHistorialError.visibility = View.VISIBLE
                orderVm.clearError()
            } else {
                binding.tvHistorialError.visibility = View.GONE
            }
        }
    }

    private fun applyFilter(source: List<WorkOrder>? = orderVm.allOrders.value) {
        val orders = source ?: emptyList()
        val filtered = when (currentFilter) {
            "dispatched" -> orders.filter { it.status == "dispatched" }
            "cancelled"  -> orders.filter { it.status == "cancelled" }
            else          -> orders
        }

        historialAdapter.updateOrders(filtered)
        val isEmpty = filtered.isEmpty()
        binding.layoutEmptyHistorial.visibility = if (isEmpty) View.VISIBLE else View.GONE
        binding.rvHistorial.visibility          = if (isEmpty) View.GONE  else View.VISIBLE

        val total = filtered.size
        val dispatched = filtered.count { it.status == "dispatched" }
        binding.tvHistorialSubtitle.text = "$total pedido(s)  ·  $dispatched completado(s)"
    }

    override fun onResume() {
        super.onResume()
        orderVm.loadAllOrders()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
