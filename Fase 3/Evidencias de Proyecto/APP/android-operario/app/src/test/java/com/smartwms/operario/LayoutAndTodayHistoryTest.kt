package com.smartwms.operario

import com.smartwms.operario.data.api.WarehouseLocationItem
import com.smartwms.operario.data.api.WorkOrder
import com.smartwms.operario.data.api.WorkOrderItem
import com.smartwms.operario.ui.OrderTimeHelper
import com.smartwms.operario.ui.PackingTableMatcher
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

class LayoutAndTodayHistoryTest {

    private val sampleLayout = listOf(
        WarehouseLocationItem(id = 1, code = "M-01", name = "Mesa de Empaque 1", locationType = "table", label = "Mesa M-01"),
        WarehouseLocationItem(id = 2, code = "M-02", name = "Mesa de Empaque 2", locationType = "table", label = "Mesa M-02"),
        WarehouseLocationItem(id = 3, code = "M-05", name = "Mesa de Empaque 5", locationType = "table", label = "Mesa M-05"),
        WarehouseLocationItem(id = 4, code = "M-10", name = "Mesa de Empaque 10", locationType = "table", label = "Mesa M-10"),
        WarehouseLocationItem(id = 5, code = "A-01", name = "Estantería A-01", locationType = "rack", label = "Zona A (A-01)")
    )

    @Test
    fun extractsOnlyTablesInNaturalOrder() {
        val tables = PackingTableMatcher.extractTables(sampleLayout)
        assertEquals(listOf("M-01", "M-02", "M-05", "M-10"), tables.map { it.code })
    }

    @Test
    fun matchesDynamicLayoutTablesAndRejectsRacksOrSyntheticOrderCodes() {
        assertEquals("M-05", PackingTableMatcher.matchTable("M-05", sampleLayout)?.code)
        assertEquals("M-10", PackingTableMatcher.matchTable(" m-10 ", sampleLayout)?.code)
        assertEquals("M-02", PackingTableMatcher.matchTable("MESA-M-02", sampleLayout)?.code)
        // Rechaza estanterías y códigos sintéticos antiguos MESA-WO-XXXX
        assertNull(PackingTableMatcher.matchTable("A-01", sampleLayout))
        assertNull(PackingTableMatcher.matchTable("MESA-WO-0001", sampleLayout))
        assertNull(PackingTableMatcher.matchTable("M-99", sampleLayout))
    }

    @Test
    fun utcNightTimestampCountsAsTodayInChileTimezone() {
        val chileZone = ZoneId.of("America/Santiago") // UTC-3 en noviembre
        val localToday = LocalDate.of(2026, 11, 27)

        // 2026-11-28T01:05:00+00:00 equivale a 2026-11-27 22:05 en Chile (HOY)
        val orderCompletedTonight = WorkOrder(
            id = 10,
            orderNumber = "WO-0010",
            status = "dispatched",
            createdByEmail = "sup@smartwms.com",
            assignedOperarioEmail = "op@smartwms.com",
            dispatchedByEmail = "op@smartwms.com",
            createdAt = "2026-11-26T15:00:00+00:00",
            dispatchedAt = "2026-11-28T01:05:00+00:00",
            cancelledAt = null,
            totalWeight = null,
            totalVolume = null,
            packagesCount = 1,
            items = listOf(WorkOrderItem(1, "SKU-001", "Producto", 5))
        )

        assertTrue(OrderTimeHelper.isOrderFromToday(orderCompletedTonight, localToday, chileZone))
        assertEquals("22:05", OrderTimeHelper.formatLocalTime(orderCompletedTonight.dispatchedAt, chileZone))
    }

    @Test
    fun calculatesDurationBetweenUtcTimestamps() {
        val duration = OrderTimeHelper.calcDuration(
            "2026-11-27T14:00:00+00:00",
            "2026-11-27T14:25:00+00:00",
            ZoneId.of("America/Santiago")
        )
        assertEquals("25 min", duration)
    }
}
