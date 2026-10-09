// ui/adapters/PickingAdapter.kt
// RecyclerView adapter para la lista de items de picking de un pedido real.
// Muestra el botón ❓ que revela la ubicación física del SKU en el almacén.

package com.smartwms.operario.ui.adapters

import android.graphics.Color
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.smartwms.operario.data.api.PickingItem
import com.smartwms.operario.databinding.ItemPickingBinding

class PickingAdapter(
    private val items: MutableList<PickingItem>,
    /**
     * Callback invocado cuando el operario toca ❓.
     * Parámetros: SKU (String), ubicación (String? — null si no tiene zona asignada).
     */
    private val onLocationClick: ((sku: String, location: String?) -> Unit)? = null
) : RecyclerView.Adapter<PickingAdapter.ViewHolder>() {

    inner class ViewHolder(private val binding: ItemPickingBinding) :
        RecyclerView.ViewHolder(binding.root) {

        fun bind(item: PickingItem, position: Int) {
            binding.tvSku.text         = item.sku
            binding.tvProductName.text = item.productName
            binding.tvQuantity.text    = "${item.pickedQuantity} / ${item.quantity} recolectadas"
            binding.tvLocation.text    = "📍 ${item.location}"

            // Botón ❓: muestra la ubicación como texto en la card o llama el callback
            binding.btnLocation.setOnClickListener {
                if (onLocationClick != null) {
                    // El Fragment maneja el diálogo
                    onLocationClick.invoke(item.sku, item.location.takeIf { it.isNotBlank() })
                } else {
                    // Fallback: toggle inline
                    if (binding.tvLocation.visibility == View.VISIBLE) {
                        binding.tvLocation.visibility = View.GONE
                    } else {
                        binding.tvLocation.visibility = View.VISIBLE
                    }
                }
            }

            if (item.isPicked) {
                binding.root.alpha           = 0.5f
                binding.ivStatus.setImageResource(android.R.drawable.ic_menu_send)
                binding.ivStatus.setColorFilter(Color.parseColor("#4ade80"))
                binding.tvQuantity.setTextColor(Color.parseColor("#4ade80"))
            } else {
                binding.root.alpha           = 1f
                binding.ivStatus.setImageResource(android.R.drawable.ic_menu_search)
                binding.ivStatus.clearColorFilter()
                binding.tvQuantity.setTextColor(Color.parseColor("#facc15"))
            }
        }
    }

    /** Llamado desde el Fragment al recibir updates del LiveData */
    fun updateItems(newItems: List<PickingItem>) {
        if (items !== newItems) {
            items.clear()
            items.addAll(newItems)
        }
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder =
        ViewHolder(ItemPickingBinding.inflate(LayoutInflater.from(parent.context), parent, false))

    override fun onBindViewHolder(holder: ViewHolder, position: Int) =
        holder.bind(items[position], position)

    override fun getItemCount() = items.size
}
