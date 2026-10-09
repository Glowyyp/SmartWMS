// ui/fragments/OrderDetailFragment.kt
package com.smartwms.operario.ui.fragments

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.navigation.fragment.findNavController
import com.smartwms.operario.R
import com.smartwms.operario.databinding.FragmentOrderDetailBinding
import com.smartwms.operario.ui.OrderViewModel
import java.text.SimpleDateFormat
import java.util.Locale

class OrderDetailFragment : Fragment() {

    private var _binding: FragmentOrderDetailBinding? = null
    private val binding get() = _binding!!

    private val orderVm: OrderViewModel by activityViewModels()

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentOrderDetailBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        binding.btnBackHistorial.setOnClickListener {
            findNavController().navigateUp()
        }

        val orderIdArg = arguments?.getInt("orderId") ?: return
        
        orderVm.allOrders.observe(viewLifecycleOwner) { orders ->
            val order = orders.find { it.id == orderIdArg }
            if (order != null) {
                binding.tvDetailTitle.text = "Pedido ${order.orderNumber}"
                
                // Estado
                when (order.status) {
                    "dispatched" -> {
                        binding.tvDetailStatus.text = "✅ Completado / Despachado"
                        binding.tvDetailStatus.setTextColor(0xFF4ade80.toInt())
                    }
                    "cancelled" -> {
                        binding.tvDetailStatus.text = "❌ Cancelado"
                        binding.tvDetailStatus.setTextColor(0xFFf87171.toInt())
                    }
                    else -> {
                        binding.tvDetailStatus.text = "● ${order.status}"
                        binding.tvDetailStatus.setTextColor(0xFFfbbf24.toInt())
                    }
                }

                binding.tvDetailCreated.text = formatDateTime(order.createdAt)
                binding.tvDetailFinished.text = formatDateTime(order.dispatchedAt)

                // Renderizar productos
                binding.llDetailProducts.removeAllViews()
                order.items.forEach { item ->
                    val textView = TextView(requireContext()).apply {
                        text = "• ${item.productName} (x${item.quantity})"
                        textSize = 14f
                        setTextColor(0xFFe2e8f0.toInt())
                        setPadding(16, 12, 16, 12)
                    }
                    binding.llDetailProducts.addView(textView)
                }

                binding.tvDetailTotal.text = "Total de productos: ${order.items.size}"
            }
        }
    }

    private fun formatDateTime(dateStr: String?): String {
        if (dateStr == null) return "—"
        return try {
            val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
            val date = sdf.parse(dateStr.take(19)) ?: return "—"
            SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.getDefault()).format(date)
        } catch (e: Exception) { "—" }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
