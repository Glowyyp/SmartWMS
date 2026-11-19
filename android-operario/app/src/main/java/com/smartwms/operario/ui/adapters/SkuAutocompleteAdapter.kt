package com.smartwms.operario.ui.adapters

import android.content.Context
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Filter
import android.widget.TextView
import androidx.core.content.ContextCompat
import com.smartwms.operario.R
import com.smartwms.operario.data.api.Product

/**
 * Adaptador de autocompletado de SKU para el módulo Putaway.
 * Muestra SKU, descripción del producto, stock físico/disponible y ubicación actual,
 * y filtra en vivo por SKU o nombre incluso con texto vacío al tocar el campo.
 */
class SkuAutocompleteAdapter(
    context: Context,
    products: List<Product> = emptyList()
) : ArrayAdapter<Product>(context, R.layout.item_sku_autocomplete, products.toMutableList()) {

    private var allProducts: List<Product> = sortProducts(products)
    private var filteredProducts: List<Product> = allProducts

    fun updateProducts(products: List<Product>) {
        allProducts = sortProducts(products)
        filteredProducts = allProducts
        notifyDataSetChanged()
    }

    private fun sortProducts(products: List<Product>): List<Product> {
        return products.sortedWith(
            compareByDescending<Product> { it.stockQuantity > 0 }.thenBy { it.sku.lowercase() }
        )
    }

    override fun getCount(): Int = filteredProducts.size

    override fun getItem(position: Int): Product? =
        filteredProducts.getOrNull(position)

    override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
        val view = convertView ?: LayoutInflater.from(context)
            .inflate(R.layout.item_sku_autocomplete, parent, false)

        val product = getItem(position) ?: return view
        val tvSku = view.findViewById<TextView>(R.id.tv_ac_sku)
        val tvStock = view.findViewById<TextView>(R.id.tv_ac_stock)
        val tvName = view.findViewById<TextView>(R.id.tv_ac_name)
        val tvLocation = view.findViewById<TextView>(R.id.tv_ac_location)

        tvSku.text = product.sku
        tvName.text = product.productName

        val hasStock = product.stockQuantity > 0
        tvStock.text = if (hasStock) {
            "Stock: ${product.stockQuantity} (Disp: ${product.availableQty})"
        } else {
            "Sin stock (0)"
        }
        tvStock.setTextColor(
            ContextCompat.getColor(
                context,
                if (hasStock) R.color.green_accent else R.color.error_color
            )
        )

        val currentLoc = product.warehouseLocation?.takeIf { it.isNotBlank() } ?: "Sin asignar"
        tvLocation.text = "Ubicación actual: $currentLoc"

        return view
    }

    override fun getFilter(): Filter = object : Filter() {
        override fun performFiltering(constraint: CharSequence?): FilterResults {
            val query = constraint?.toString()?.trim()?.lowercase().orEmpty()
            val matches = if (query.isEmpty()) {
                allProducts
            } else {
                allProducts.filter {
                    it.sku.lowercase().contains(query) ||
                        it.productName.lowercase().contains(query)
                }
            }
            return FilterResults().apply {
                values = matches
                count = matches.size
            }
        }

        @Suppress("UNCHECKED_CAST")
        override fun publishResults(constraint: CharSequence?, results: FilterResults?) {
            filteredProducts = (results?.values as? List<Product>) ?: emptyList()
            notifyDataSetChanged()
        }

        override fun convertResultToString(resultValue: Any?): CharSequence {
            return (resultValue as? Product)?.sku ?: ""
        }
    }
}
