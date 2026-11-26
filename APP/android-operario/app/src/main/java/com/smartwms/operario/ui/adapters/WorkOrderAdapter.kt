// ui/adapters/WorkOrderAdapter.kt
// RecyclerView adapter para la lista de pedidos de bodega pendientes

package com.smartwms.operario.ui.adapters

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.smartwms.operario.data.api.WorkOrder
import com.smartwms.operario.databinding.ItemWorkOrderBinding
import java.text.SimpleDateFormat
import java.util.Locale

class WorkOrderAdapter(
    private var orders: List<WorkOrder>,
    private val onClick: (WorkOrder) -> Unit
) : RecyclerView.Adapter<WorkOrderAdapter.ViewHolder>() {

    private val dateFormat = SimpleDateFormat("dd/MM HH:mm", Locale.getDefault())
    private val isoFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())

    inner class ViewHolder(private val binding: ItemWorkOrderBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(order: WorkOrder) {
            binding.tvOrderNumber.text = order.orderNumber

            val statusLabel = when (order.status) {
                "pending"    -> "Pendiente"
                "dispatched" -> "Despachado"
                "cancelled"  -> "Cancelado"
                else         -> order.status
            }
            binding.tvOrderStatus.text = statusLabel

            binding.tvCreatedBy.text = "Creado por: ${order.createdByEmail ?: "—"}"

            val itemsCount = order.items.size
            val skuList = order.items.take(3).joinToString(", ") { "${it.sku} ×${it.quantity}" }
            val moreText = if (itemsCount > 3) " +${itemsCount - 3} más" else ""
            binding.tvItemsPreview.text = "$itemsCount SKU(s): $skuList$moreText"

            try {
                val date = isoFormat.parse(order.createdAt.replace("Z", "").take(19))
                binding.tvCreatedAt.text = if (date != null) "📅 ${dateFormat.format(date)}" else order.createdAt
            } catch (_: Exception) {
                binding.tvCreatedAt.text = order.createdAt
            }

            binding.root.setOnClickListener { onClick(order) }
        }
    }

    fun updateOrders(newOrders: List<WorkOrder>) {
        orders = newOrders
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder =
        ViewHolder(ItemWorkOrderBinding.inflate(LayoutInflater.from(parent.context), parent, false))

    override fun onBindViewHolder(holder: ViewHolder, position: Int) =
        holder.bind(orders[position])

    override fun getItemCount() = orders.size
}
