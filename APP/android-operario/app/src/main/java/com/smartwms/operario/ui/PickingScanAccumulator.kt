package com.smartwms.operario.ui

/**
 * Acumulador thread-safe para el escaneo de productos en Picking.
 *
 * Reglas:
 *  - Cada escaneo válido suma exactamente +1 unidad al SKU correspondiente.
 *  - Reconoce productos repetidos (insensible a mayúsculas/minúsculas) y acumula
 *    en la clave canónica del ítem sin generar registros duplicados.
 *  - Nunca supera la cantidad requerida del pedido.
 *  - Sincronizado para evitar condiciones de carrera ante escaneos rápidos consecutivos.
 */
class PickingScanAccumulator {

    data class OrderItemSpec(
        val sku: String,
        val productName: String,
        val requiredQuantity: Int
    )

    sealed class ScanResult {
        object EmptyCode : ScanResult()
        data class InvalidCode(val rawCode: String) : ScanResult()
        data class AlreadyComplete(
            val sku: String,
            val productName: String,
            val requiredQuantity: Int
        ) : ScanResult()

        data class Added(
            val sku: String,
            val productName: String,
            val newQuantity: Int,
            val requiredQuantity: Int,
            val orderComplete: Boolean
        ) : ScanResult()
    }

    private val lock = Any()
    private val pickedBySku = LinkedHashMap<String, Int>()

    fun reset(initialCounts: Map<String, Int> = emptyMap()): Map<String, Int> = synchronized(lock) {
        pickedBySku.clear()
        initialCounts.forEach { (sku, qty) ->
            if (qty > 0) {
                pickedBySku[sku] = qty
            }
        }
        LinkedHashMap(pickedBySku)
    }

    fun snapshot(): Map<String, Int> = synchronized(lock) {
        LinkedHashMap(pickedBySku)
    }

    fun getQuantity(sku: String): Int = synchronized(lock) {
        pickedBySku[sku] ?: 0
    }

    /**
     * Consolida la cantidad requerida por SKU (si existieran líneas repetidas) y
     * suma exactamente +1 unidad al producto escaneado.
     */
    fun recordScan(rawCode: String, orderItems: List<OrderItemSpec>): ScanResult = synchronized(lock) {
        val cleanCode = rawCode.trim()
        if (cleanCode.isEmpty()) return@synchronized ScanResult.EmptyCode

        val matchingItems = orderItems.filter { it.sku.trim().equals(cleanCode, ignoreCase = true) }
        if (matchingItems.isEmpty()) return@synchronized ScanResult.InvalidCode(cleanCode)

        val canonicalSku = matchingItems.first().sku
        val productName = matchingItems.first().productName
        val requiredQty = matchingItems.sumOf { it.requiredQuantity }

        val currentQty = pickedBySku[canonicalSku] ?: 0
        if (currentQty >= requiredQty) {
            return@synchronized ScanResult.AlreadyComplete(
                sku = canonicalSku,
                productName = productName,
                requiredQuantity = requiredQty
            )
        }

        val updatedQty = currentQty + 1
        pickedBySku[canonicalSku] = updatedQty

        val complete = isCompleteLocked(orderItems)
        ScanResult.Added(
            sku = canonicalSku,
            productName = productName,
            newQuantity = updatedQty,
            requiredQuantity = requiredQty,
            orderComplete = complete
        )
    }

    /**
     * Agrega una cantidad controlada (por defecto 1) al SKU canónico.
     * Devuelve el nuevo snapshot si se aplicó, o null si excede maxQuantity o es inválida.
     */
    fun addQuantity(sku: String, maxQuantity: Int, quantityToAdd: Int = 1): Map<String, Int>? = synchronized(lock) {
        if (quantityToAdd <= 0) return@synchronized null
        val currentQty = pickedBySku[sku] ?: 0
        if (currentQty + quantityToAdd > maxQuantity) return@synchronized null
        pickedBySku[sku] = currentQty + quantityToAdd
        LinkedHashMap(pickedBySku)
    }

    fun isOrderComplete(orderItems: List<OrderItemSpec>): Boolean = synchronized(lock) {
        isCompleteLocked(orderItems)
    }

    private fun isCompleteLocked(orderItems: List<OrderItemSpec>): Boolean {
        if (orderItems.isEmpty()) return false
        val requiredBySku = LinkedHashMap<String, Int>()
        for (item in orderItems) {
            requiredBySku[item.sku] = (requiredBySku[item.sku] ?: 0) + item.requiredQuantity
        }
        return requiredBySku.all { (sku, req) -> (pickedBySku[sku] ?: 0) >= req }
    }
}
