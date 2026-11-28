package com.smartwms.operario.ui

import com.smartwms.operario.data.api.WarehouseLocationItem

/**
 * Resuelve y valida dinámicamente las mesas de empaque configuradas en el Layout
 * del Supervisor (sin límite fijo ni códigos sintéticos MESA-WO-XXXX).
 */
object PackingTableMatcher {

    private val naturalNumberRegex = Regex("(\\d+)")

    /**
     * Filtra únicamente las ubicaciones de tipo "table" (mesas de bodega)
     * ordenadas naturalmente por código (M-01, M-02, ..., M-10).
     */
    fun extractTables(locations: List<WarehouseLocationItem>): List<WarehouseLocationItem> {
        return locations
            .filter { it.locationType.equals("table", ignoreCase = true) }
            .sortedWith(compareBy<WarehouseLocationItem> { sortKeyPrefix(it.code) }
                .thenBy { sortKeyNumber(it.code) }
                .thenBy { it.code.uppercase() })
    }

    /**
     * Valida si un código escaneado (QR/barras) o ingresado manualmente corresponde
     * a una mesa activa del Layout del Supervisor.
     * Rechaza estanterías (racks) y códigos inexistentes.
     */
    fun matchTable(
        rawCode: String,
        locations: List<WarehouseLocationItem>
    ): WarehouseLocationItem? {
        val clean = rawCode.trim()
        if (clean.isEmpty()) return null

        val tables = extractTables(locations)
        if (tables.isEmpty()) return null

        // 1. Coincidencia exacta por código de mesa (ej: "M-01", "M-05", "MESA-SUR")
        tables.firstOrNull { it.code.trim().equals(clean, ignoreCase = true) }?.let { return it }

        // 2. Tolerancia si el código trae prefijo "MESA-" delante del código real (ej: "MESA-M-01")
        if (clean.startsWith("MESA-", ignoreCase = true)) {
            val withoutPrefix = clean.substring(5).trim()
            if (withoutPrefix.isNotEmpty()) {
                tables.firstOrNull { it.code.trim().equals(withoutPrefix, ignoreCase = true) }?.let { return it }
            }
        }

        // 3. Coincidencia exacta por nombre de mesa (ej: "Mesa de Empaque 5")
        tables.firstOrNull { it.name.trim().equals(clean, ignoreCase = true) }?.let { return it }

        return null
    }

    private fun sortKeyPrefix(code: String): String {
        return code.uppercase().replace(naturalNumberRegex, "")
    }

    private fun sortKeyNumber(code: String): Int {
        return naturalNumberRegex.find(code)?.groupValues?.get(1)?.toIntOrNull() ?: Int.MAX_VALUE
    }
}
